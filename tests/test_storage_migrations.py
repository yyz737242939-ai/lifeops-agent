from __future__ import annotations

import unittest

from app.common.errors import MigrationError
from app.storage.migrations import get_schema_version, migrate
from app.storage.schema import CURRENT_SCHEMA_VERSION, MIGRATIONS, SchemaMigration
from tests.helpers import create_test_connection


class StorageMigrationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection(migrate_schema=False)

    def tearDown(self) -> None:
        self.conn.close()

    def test_empty_database_starts_at_schema_version_zero(self) -> None:
        self.assertEqual(get_schema_version(self.conn), 0)

    def test_migrate_creates_initial_storage_tables(self) -> None:
        report = migrate(self.conn)

        self.assertEqual(report.previous_version, 0)
        self.assertEqual(report.current_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(report.applied_versions, (1, 2, 3, 4, 5, 6, 7, 8))
        self.assertEqual(get_schema_version(self.conn), CURRENT_SCHEMA_VERSION)
        self.assert_tables_exist(
            "schema_migrations",
            "run_records",
            "tool_calls",
            "research_sources",
            "research_source_snapshots",
            "research_topics",
            "research_notes",
            "research_briefs",
            "research_brief_sources",
            "research_links",
            "research_revisions",
            "travel_itineraries",
            "trips",
            "travel_constraints",
            "travel_itinerary_items",
            "travel_decisions",
            "travel_knowledge_refs",
        )

    def test_migrate_is_idempotent(self) -> None:
        first = migrate(self.conn)
        second = migrate(self.conn)

        self.assertEqual(first.applied_versions, (1, 2, 3, 4, 5, 6, 7, 8))
        self.assertEqual(second.previous_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(second.current_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(second.applied_versions, ())

        rows = self.conn.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()
        self.assertEqual(rows["count"], 8)

    def test_v5_migrates_existing_source_and_brief_reference_to_snapshot(self) -> None:
        migrate(self.conn, MIGRATIONS[:4])
        self.conn.execute(
            """INSERT INTO research_sources
               (id, source_key, url, title, summary, content_hash,
                fetched_at, provenance, created_at)
               VALUES ('source-old', 'old', 'https://example.com/old', 'Old',
                       'Old summary', 'old-hash', '2026-07-11T00:00:00+00:00',
                       'fixture:old', '2026-07-11T00:00:00+00:00')"""
        )
        self.conn.execute(
            """INSERT INTO research_briefs (id, title, body, provenance, created_at)
               VALUES ('brief-old', 'Old Brief', 'Body', 'fixture:old',
                       '2026-07-11T00:00:00+00:00')"""
        )
        self.conn.execute(
            """INSERT INTO research_brief_sources (brief_id, source_id, position)
               VALUES ('brief-old', 'source-old', 0)"""
        )
        self.conn.commit()

        report = migrate(self.conn)

        self.assertEqual(report.applied_versions, (5, 6, 7, 8))
        snapshot = self.conn.execute(
            "SELECT id, source_id, content_hash FROM research_source_snapshots"
        ).fetchone()
        brief_ref = self.conn.execute(
            "SELECT source_id, snapshot_id FROM research_brief_sources"
        ).fetchone()
        self.assertEqual(snapshot["source_id"], "source-old")
        self.assertEqual(snapshot["content_hash"], "old-hash")
        self.assertEqual(brief_ref["snapshot_id"], snapshot["id"])

    def test_v7_preserves_v6_travel_items_and_unlinked_decisions(self) -> None:
        migrate(self.conn, MIGRATIONS[:6])
        now = "2026-07-13T00:00:00+00:00"
        self.conn.execute(
            """INSERT INTO trips
               (id, title, status, version, created_at, updated_at, archived_at)
               VALUES ('trip-v6', 'V6 Trip', 'active', 1, ?, ?, NULL)""",
            (now, now),
        )
        self.conn.execute(
            """INSERT INTO travel_itineraries
               (id, destination, transport, lodging, summary, observed_at,
                expires_at, provenance, created_at, trip_id, draft_id,
                idempotency_key, version)
               VALUES ('itinerary-v6', 'Tokyo', 'Train', 'Hotel', 'Summary',
                       ?, '2027-01-01T00:00:00+00:00', 'fixture:v6', ?,
                       'trip-v6', 'draft-v6', 'key-v6', 1)""",
            (now, now),
        )
        self.conn.execute(
            """INSERT INTO travel_itinerary_items
               (id, itinerary_id, day_number, title, item_type, starts_at,
                ends_at, source_candidate_id, notes, created_at)
               VALUES ('item-v6', 'itinerary-v6', 1, 'Train', 'transport',
                       ?, '2026-10-01T01:00:00+00:00', 'candidate-v6', NULL, ?)""",
            (now, now),
        )
        self.conn.execute(
            """INSERT INTO travel_decisions
               (id, trip_id, kind, selected_candidate_ids_json, rationale, decided_at)
               VALUES ('decision-v6', 'trip-v6', 'itinerary',
                       '[""candidate-v6""]', 'V6 decision', ?)""",
            (now,),
        )
        self.conn.commit()

        report = migrate(self.conn)

        self.assertEqual(report.applied_versions, (7, 8))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itinerary_items").fetchone()[0],
            1,
        )
        decision = self.conn.execute(
            "SELECT itinerary_id FROM travel_decisions WHERE id = 'decision-v6'"
        ).fetchone()
        self.assertIsNone(decision["itinerary_id"])

    def test_newer_database_version_is_rejected(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (99, 'future_schema', '2026-07-08T00:00:00+00:00')
            """
        )

        with self.assertRaises(MigrationError) as caught:
            migrate(self.conn)

        self.assertEqual(caught.exception.code, "schema_version_too_new")

    def test_failed_migration_rolls_back_version_record(self) -> None:
        broken = (
            SchemaMigration(
                version=1,
                name="broken",
                sql="CREATE TABLE broken (id TEXT PRIMARY KEY); INSERT INTO missing_table VALUES (1);",
            ),
        )

        with self.assertRaises(MigrationError) as caught:
            migrate(self.conn, broken)

        self.assertEqual(caught.exception.code, "schema_migration_failed")
        self.assertEqual(get_schema_version(self.conn), 0)
        self.assert_table_missing("broken")

    def assert_tables_exist(self, *table_names: str) -> None:
        existing = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table_name in table_names:
            self.assertIn(table_name, existing)

    def assert_table_missing(self, table_name: str) -> None:
        row = self.conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
