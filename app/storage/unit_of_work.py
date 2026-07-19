"""SQLite transaction boundary helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from app.common.errors import StorageError
from app.storage.sqlite import connect_sqlite


class SqliteUnitOfWork:
    """Context manager that owns a single SQLite transaction boundary."""

    def __init__(self, conn: sqlite3.Connection, *, close_on_exit: bool = False) -> None:
        self.conn = conn
        self._close_on_exit = close_on_exit
        self._active = False

    @classmethod
    def connect(cls, path: str | Path | None = None) -> "SqliteUnitOfWork":
        return cls(connect_sqlite(path), close_on_exit=True)

    def __enter__(self) -> "SqliteUnitOfWork":
        if self._active:
            raise StorageError(
                "SQLite unit of work is already active.",
                code="unit_of_work_already_active",
            )
        if self.conn.in_transaction:
            raise StorageError(
                "SQLite connection already has an active transaction.",
                code="sqlite_transaction_already_active",
            )

        self.conn.execute("BEGIN")
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self._active = False
            if self._close_on_exit:
                self.conn.close()

        return False

    def commit(self) -> None:
        try:
            self.conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to commit SQLite transaction.",
                code="sqlite_commit_failed",
            ) from exc

    def rollback(self) -> None:
        try:
            self.conn.rollback()
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to roll back SQLite transaction.",
                code="sqlite_rollback_failed",
            ) from exc
