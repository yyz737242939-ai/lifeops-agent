from __future__ import annotations

import unittest

from app.common.errors import StorageError
from app.storage.unit_of_work import SqliteUnitOfWork
from tests.helpers import create_test_connection


class SqliteUnitOfWorkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()

    def tearDown(self) -> None:
        self.conn.close()

    def test_context_commits_when_no_exception_occurs(self) -> None:
        with SqliteUnitOfWork(self.conn) as uow:
            uow.conn.execute(
                """
                INSERT INTO run_records (id, started_at, status, created_at)
                VALUES ('run_commit', '2026-07-08T00:00:00+00:00', 'running', '2026-07-08T00:00:00+00:00')
                """
            )

        row = self.conn.execute(
            "SELECT id FROM run_records WHERE id = 'run_commit'"
        ).fetchone()
        self.assertEqual(row["id"], "run_commit")

    def test_context_rolls_back_when_exception_occurs(self) -> None:
        with self.assertRaises(RuntimeError):
            with SqliteUnitOfWork(self.conn) as uow:
                uow.conn.execute(
                    """
                    INSERT INTO run_records (id, started_at, status, created_at)
                    VALUES ('run_rollback', '2026-07-08T00:00:00+00:00', 'running', '2026-07-08T00:00:00+00:00')
                    """
                )
                raise RuntimeError("fail this unit")

        row = self.conn.execute(
            "SELECT id FROM run_records WHERE id = 'run_rollback'"
        ).fetchone()
        self.assertIsNone(row)

    def test_rejects_entry_when_connection_already_has_transaction(self) -> None:
        self.conn.execute("BEGIN")
        try:
            with self.assertRaises(StorageError) as caught:
                with SqliteUnitOfWork(self.conn):
                    pass
        finally:
            self.conn.rollback()

        self.assertEqual(caught.exception.code, "sqlite_transaction_already_active")

    def test_connect_classmethod_opens_own_connection(self) -> None:
        with SqliteUnitOfWork.connect(":memory:") as uow:
            uow.conn.execute("CREATE TABLE example (id TEXT PRIMARY KEY)")
            uow.conn.execute(
                "INSERT INTO example (id) VALUES ('row_1')"
            )


if __name__ == "__main__":
    unittest.main()
