from __future__ import annotations

import unittest

from app.common.time import utc_now_iso
from app.domains.research.models import FetchedSourceDocument
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from tests.helpers import create_test_connection


class _FakeContentPort:
    def fetch(self, source_key: str) -> FetchedSourceDocument:
        return FetchedSourceDocument(
            document_id="document_1",
            observation_id="observation_1",
            source_key=source_key,
            title="Daily Papers",
            url="https://huggingface.co/papers",
            content_type="text/html",
            content='<a href="/papers/1">Agent workflow research</a>',
            content_hash="hash",
            fetched_at=utc_now_iso(),
            provenance="fixture:content",
        )


class ResearchContentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.service = ResearchService(
            FixtureResearchSourcePort({}),
            ResearchRepository(self.conn),
            content_port=_FakeContentPort(),
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_fetch_then_parse_uses_request_local_document_id(self) -> None:
        document = self.service.fetch_content("hf_daily_papers")
        item_set = self.service.parse_items(document.document_id)

        self.assertEqual(item_set.items[0].title, "Agent workflow research")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0], 0
        )

    def test_unknown_document_id_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            self.service.parse_items("unknown")


if __name__ == "__main__":
    unittest.main()
