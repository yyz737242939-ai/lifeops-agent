from __future__ import annotations

import unittest

from app.storage.migrations import get_schema_version
from app.storage.schema import CURRENT_SCHEMA_VERSION
from tests.helpers import create_test_connection, insert_test_run_record


class TestDatabaseHelpersTest(unittest.TestCase):
    def test_create_test_connection_migrates_schema_by_default(self) -> None:
        conn = create_test_connection()
        try:
            self.assertEqual(get_schema_version(conn), CURRENT_SCHEMA_VERSION)
        finally:
            conn.close()

    def test_create_test_connection_can_skip_schema_migration(self) -> None:
        conn = create_test_connection(migrate_schema=False)
        try:
            self.assertEqual(get_schema_version(conn), 0)
        finally:
            conn.close()

    def test_insert_test_run_record_commits_fixture(self) -> None:
        conn = create_test_connection()
        try:
            insert_test_run_record(conn, "run_fixture")
            row = conn.execute(
                "SELECT id FROM run_records WHERE id = 'run_fixture'"
            ).fetchone()
            self.assertEqual(row["id"], "run_fixture")
            self.assertFalse(conn.in_transaction)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
