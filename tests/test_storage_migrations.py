from __future__ import annotations

import unittest

from app.common.errors import MigrationError
from app.storage.migrations import get_schema_version, migrate
from app.storage.schema import CURRENT_SCHEMA_VERSION, SchemaMigration
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
        self.assertEqual(report.applied_versions, (1, 2, 3))
        self.assertEqual(get_schema_version(self.conn), CURRENT_SCHEMA_VERSION)
        self.assert_tables_exist(
            "schema_migrations",
            "run_records",
            "tool_calls",
            "research_sources",
            "travel_itineraries",
        )

    def test_migrate_is_idempotent(self) -> None:
        first = migrate(self.conn)
        second = migrate(self.conn)

        self.assertEqual(first.applied_versions, (1, 2, 3))
        self.assertEqual(second.previous_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(second.current_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(second.applied_versions, ())

        rows = self.conn.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()
        self.assertEqual(rows["count"], 3)

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
