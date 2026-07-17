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
        self.assertEqual(report.applied_versions, (1, 2, 3, 4))
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
            "plan_runs",
            "plan_steps",
            "memory_index",
        )

    def test_migrate_is_idempotent(self) -> None:
        first = migrate(self.conn)
        second = migrate(self.conn)

        self.assertEqual(first.applied_versions, (1, 2, 3, 4))
        self.assertEqual(second.previous_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(second.current_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(second.applied_versions, ())

        rows = self.conn.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()
        self.assertEqual(rows["count"], 4)

    def test_v1_database_migrates_to_current_without_rewriting_v1(self) -> None:
        first = migrate(self.conn, MIGRATIONS[:1])
        second = migrate(self.conn)

        self.assertEqual(first.applied_versions, (1,))
        self.assertEqual(second.applied_versions, (2, 3, 4))
        self.assertEqual(get_schema_version(self.conn), CURRENT_SCHEMA_VERSION)
        self.assert_tables_exist("plan_runs", "plan_steps")
        self.assertIn("confirmed_constraints_json", self.column_names("plan_runs"))

    def test_v2_database_adds_confirmed_constraints_without_rewriting_plan_tables(self) -> None:
        migrate(self.conn, MIGRATIONS[:2])
        before_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'plan_steps'"
        ).fetchone()["sql"]

        report = migrate(self.conn)

        after_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'plan_steps'"
        ).fetchone()["sql"]
        self.assertEqual(report.applied_versions, (3, 4))
        self.assertEqual(before_sql, after_sql)
        self.assertIn("confirmed_constraints_json", self.column_names("plan_runs"))

    def test_v3_database_adds_memory_index_without_rewriting_plan_tables(self) -> None:
        migrate(self.conn, MIGRATIONS[:3])
        before_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'plan_runs'"
        ).fetchone()["sql"]

        report = migrate(self.conn)

        after_sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'plan_runs'"
        ).fetchone()["sql"]
        self.assertEqual(report.applied_versions, (4,))
        self.assertEqual(before_sql, after_sql)
        self.assertEqual(
            self.column_names("memory_index"),
            (
                "memory_id",
                "version",
                "status",
                "relative_path",
                "content_hash",
                "tags_json",
                "created_at",
                "updated_at",
                "supersedes_memory_id",
                "supersedes_version",
                "source_session_id",
                "source_turn_id",
                "source_run_id",
                "source_tool_call_id",
                "confirmation_ref",
                "evidence_ref",
            ),
        )
        self.assertNotIn("content", self.column_names("memory_index"))

    def test_squashed_v1_has_the_final_research_and_travel_shapes(self) -> None:
        migrate(self.conn)

        self.assertEqual(
            self.column_names("research_sources"),
            ("id", "source_key", "url", "title", "source_type", "created_at"),
        )
        self.assertEqual(
            self.column_names("research_source_snapshots"),
            (
                "id",
                "source_id",
                "summary",
                "content_hash",
                "fetched_at",
                "published_at",
                "provenance",
                "created_at",
            ),
        )
        self.assertEqual(
            self.column_names("research_brief_sources"),
            ("brief_id", "source_id", "snapshot_id", "position"),
        )
        self.assertEqual(
            self.column_names("travel_itineraries"),
            (
                "id",
                "destination",
                "transport",
                "lodging",
                "summary",
                "observed_at",
                "expires_at",
                "provenance",
                "created_at",
                "trip_id",
                "draft_id",
                "idempotency_key",
                "version",
            ),
        )
        self.assertEqual(
            self.column_names("travel_itinerary_items"),
            (
                "id",
                "itinerary_id",
                "day_number",
                "title",
                "item_type",
                "starts_at",
                "ends_at",
                "source_candidate_id",
                "notes",
                "created_at",
            ),
        )
        self.assertEqual(
            self.column_names("travel_decisions"),
            (
                "id",
                "trip_id",
                "itinerary_id",
                "kind",
                "selected_candidate_ids_json",
                "rationale",
                "decided_at",
            ),
        )
        self.assertEqual(
            self.column_names("travel_knowledge_refs"),
            ("id", "trip_id", "domain", "item_kind", "item_id", "created_at"),
        )
        legacy_tables = self.conn.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table'
                 AND (name LIKE '%_legacy' OR name LIKE '%_v6' OR name LIKE '%_v7')"""
        ).fetchall()
        self.assertEqual(legacy_tables, [])

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

    def column_names(self, table_name: str) -> tuple[str, ...]:
        return tuple(
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        )


if __name__ == "__main__":
    unittest.main()
