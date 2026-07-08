from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.common.errors import StorageError
from app.storage.sqlite import connect_sqlite


class SqliteConnectionTest(unittest.TestCase):
    def test_connect_sqlite_supports_memory_database(self) -> None:
        conn = connect_sqlite(":memory:")
        try:
            self.assertIs(conn.row_factory, sqlite3.Row)
            enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(enabled, 1)
        finally:
            conn.close()

    def test_rows_can_be_accessed_by_column_name(self) -> None:
        conn = connect_sqlite(":memory:")
        try:
            row = conn.execute("SELECT 42 AS answer").fetchone()
            self.assertEqual(row["answer"], 42)
        finally:
            conn.close()

    def test_connect_sqlite_creates_parent_directory_for_file_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nested" / "lifeops.sqlite3"

            conn = connect_sqlite(db_path)
            conn.close()

            self.assertTrue(db_path.exists())

    def test_blank_path_is_rejected(self) -> None:
        with self.assertRaises(StorageError) as caught:
            connect_sqlite(" ")

        self.assertEqual(caught.exception.code, "sqlite_path_empty")

    def test_none_path_uses_default_config_database_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path.cwd()
            try:
                # Exercise the default config path without touching repo-local data/.
                temp_root = Path(tmpdir)
                (temp_root / "config").mkdir()
                (temp_root / "config" / "default.json").write_text(
                    '{"database":{"path":"tmp.sqlite3"}}',
                    encoding="utf-8",
                )
                import os

                os.chdir(temp_root)
                conn = connect_sqlite()
                conn.close()

                self.assertTrue((temp_root / "tmp.sqlite3").exists())
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
