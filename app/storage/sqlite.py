"""SQLite connection setup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.common.config import load_app_config
from app.common.errors import StorageError

MEMORY_DATABASE = ":memory:"


def connect_sqlite(path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection configured for the current runtime."""
    if path is None:
        path = load_app_config().database_path

    database_path = _normalize_database_path(path)
    try:
        if database_path != MEMORY_DATABASE:
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(database_path)
        initialize_connection(conn)
        return conn
    except sqlite3.Error as exc:
        raise StorageError(
            "Failed to open SQLite database.",
            code="sqlite_connect_failed",
            details={"path": str(path)},
        ) from exc
    except OSError as exc:
        raise StorageError(
            "Failed to prepare SQLite database path.",
            code="sqlite_path_prepare_failed",
            details={"path": str(path)},
        ) from exc


def initialize_connection(conn: sqlite3.Connection) -> None:
    """Apply runtime defaults to a SQLite connection."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")


def _normalize_database_path(path: str | Path) -> str:
    if isinstance(path, Path):
        path = str(path)
    if path == MEMORY_DATABASE:
        return path
    if not path or not str(path).strip():
        raise StorageError(
            "SQLite database path must be non-empty.",
            code="sqlite_path_empty",
        )
    return str(path)
