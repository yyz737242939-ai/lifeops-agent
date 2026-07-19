from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from app.common.errors import StorageError
from app.common.time import utc_now_iso
from app.domains.research.models import (
    ExternalObservation,
    FetchedSourceDocument,
    ResearchBriefDraft,
)
from app.domains.research.ports import (
    FixtureResearchSourcePort,
    HuggingFaceResearchContentPort,
    ResearchExternalSourceError,
)
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from tests.helpers import create_test_connection


FIXTURE_ROOT = Path("tests/fixtures/research")


class _EmptyContentPort:
    def fetch(self, source_key: str) -> FetchedSourceDocument:
        return FetchedSourceDocument(
            document_id="empty-document",
            observation_id="empty-observation",
            source_key=source_key,
            title="Empty fixture",
            url="https://huggingface.co/papers",
            content_type="text/html",
            content=(FIXTURE_ROOT / "empty_list.html").read_text(encoding="utf-8"),
            content_hash="empty-hash",
            fetched_at=utc_now_iso(),
            provenance="fixture:empty-list",
        )


class ResearchResilienceFixturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repository = ResearchRepository(self.conn)
        self.provider_cases = self._read_cases("provider_failures.json")
        self.integrity_cases = self._read_cases("reference_integrity_cases.json")

    def tearDown(self) -> None:
        self.conn.close()

    def test_provider_failure_fixtures_fail_closed(self) -> None:
        port = HuggingFaceResearchContentPort(Path("app/skills/research"))
        observed: dict[str, str] = {}
        with patch("app.domains.research.ports.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(ResearchExternalSourceError) as timeout:
                port.fetch("hf_blog")
            observed["timeout"] = str(timeout.exception.code)
        with patch(
            "app.domains.research.ports.urlopen",
            side_effect=HTTPError(
                "https://huggingface.co/blog", 503, "Unavailable", {}, None
            ),
        ):
            with self.assertRaises(ResearchExternalSourceError) as http_error:
                port.fetch("hf_blog")
            observed["http_503"] = str(http_error.exception.code)

        service = ResearchService(
            FixtureResearchSourcePort({}),
            self.repository,
            content_port=_EmptyContentPort(),
        )
        document = service.fetch_content("hf_daily_papers")
        with self.assertRaises(ValueError):
            service.parse_items(document.document_id)
        observed["empty_parse"] = "no_items_parsed"

        self.assertEqual(
            observed,
            {case["case_id"]: case["expected_code"] for case in self.provider_cases},
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0], 0
        )

    def test_reference_integrity_fixtures_reject_invalid_writes(self) -> None:
        observed: dict[str, str] = {}
        topic = self.repository.create_topic("Integrity", "Fixture topic")
        try:
            self.repository.link_items(
                "topic", topic.topic_id, "note", "missing-note", "related"
            )
        except ValueError as exc:
            observed["missing_link_target"] = exc.__class__.__name__

        try:
            self.repository.save_brief(
                ResearchBriefDraft(
                    "integrity-draft",
                    "Integrity Brief",
                    "Body",
                    ("https://example.com/missing",),
                    "fixture:integrity",
                    utc_now_iso(),
                )
            )
        except ValueError as exc:
            observed["unsaved_brief_source"] = exc.__class__.__name__

        observation = ExternalObservation(
            "integrity-observation",
            "fixture-integrity",
            "Integrity Source",
            "https://example.com/duplicate",
            "Summary",
            "integrity-hash",
            utc_now_iso(),
            "fixture:integrity",
        )
        self.repository.save_source(observation)
        try:
            self.repository.save_source(observation)
        except StorageError as exc:
            observed["duplicate_source_url"] = str(exc.code)

        expected = {
            case["case_id"]: case.get("expected_code", case.get("expected_error"))
            for case in self.integrity_cases
        }
        self.assertEqual(observed, expected)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_links").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_briefs").fetchone()[0], 0
        )

    @staticmethod
    def _read_cases(name: str) -> list[dict[str, str]]:
        raw = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1 or not isinstance(raw.get("cases"), list):
            raise ValueError(f"Invalid Research fixture: {name}")
        return raw["cases"]


if __name__ == "__main__":
    unittest.main()
