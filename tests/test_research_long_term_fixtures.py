from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.domains.research.read_models import ResearchReadService
from app.domains.research.repository import ResearchRepository
from tests.helpers import create_test_connection


FIXTURE_ROOT = Path("tests/fixtures/research")


class ResearchLongTermFixturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.read_service = ResearchReadService(ResearchRepository(self.conn))
        self.seed = json.loads(
            (FIXTURE_ROOT / "knowledge_seed.json").read_text(encoding="utf-8")
        )
        self._insert_seed()

    def tearDown(self) -> None:
        self.conn.close()

    def test_seed_contains_hundreds_of_saved_items(self) -> None:
        expected = sum(self.seed["counts"].values())
        actual = sum(
            self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("research_sources", "research_notes", "research_briefs")
        )

        self.assertEqual(expected, 380)
        self.assertEqual(actual, expected)

    def test_pagination_is_stable_and_non_overlapping(self) -> None:
        kinds = ("source", "note", "brief")
        first = self.read_service.search_saved_items(
            "Seed Agent", kinds, limit=50, offset=0
        )
        second = self.read_service.search_saved_items(
            "Seed Agent", kinds, limit=50, offset=50
        )
        repeated = self.read_service.search_saved_items(
            "Seed Agent", kinds, limit=50, offset=0
        )

        self.assertEqual(first, repeated)
        self.assertEqual(len(first), 50)
        self.assertEqual(len(second), 50)
        self.assertTrue(
            {item.item_id for item in first}.isdisjoint(
                item.item_id for item in second
            )
        )

    def test_context_budget_is_stable_at_seed_scale(self) -> None:
        first = self.read_service.query_context_candidates("Seed Agent", 600)
        second = self.read_service.query_context_candidates("Seed Agent", 600)

        self.assertEqual(first, second)
        self.assertLessEqual(sum(item.estimated_chars for item in first), 600)

    def _insert_seed(self) -> None:
        timestamp = "2026-07-12T00:00:00+00:00"
        counts = self.seed["counts"]
        templates = self.seed["templates"]
        self.conn.executemany(
            """INSERT INTO research_sources
               (id, source_key, url, title, source_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                (
                    f"seed-source-{index:03d}",
                    "seed",
                    f"https://example.com/seed/{index}",
                    templates["source_title"].format(index=index),
                    "web_page",
                    timestamp,
                )
                for index in range(counts["sources"])
            ),
        )
        self.conn.executemany(
            """INSERT INTO research_source_snapshots
               (id, source_id, summary, content_hash, fetched_at,
                published_at, provenance, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    f"seed-snapshot-{index:03d}",
                    f"seed-source-{index:03d}",
                    f"Seed Agent source content {index}",
                    f"seed-hash-{index}",
                    timestamp,
                    None,
                    "fixture:long-term-seed",
                    timestamp,
                )
                for index in range(counts["sources"])
            ),
        )
        self.conn.executemany(
            "INSERT INTO research_notes (id, title, body, created_at) VALUES (?, ?, ?, ?)",
            (
                (
                    f"seed-note-{index:03d}",
                    templates["note_title"].format(index=index),
                    f"Seed Agent note content {index}",
                    timestamp,
                )
                for index in range(counts["notes"])
            ),
        )
        self.conn.executemany(
            """INSERT INTO research_briefs
               (id, title, body, provenance, created_at) VALUES (?, ?, ?, ?, ?)""",
            (
                (
                    f"seed-brief-{index:03d}",
                    templates["brief_title"].format(index=index),
                    f"Seed Agent brief content {index}",
                    "fixture:long-term-seed",
                    timestamp,
                )
                for index in range(counts["briefs"])
            ),
        )


if __name__ == "__main__":
    unittest.main()
