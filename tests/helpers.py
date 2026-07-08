from __future__ import annotations

import sqlite3

from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


def create_test_connection(*, migrate_schema: bool = True) -> sqlite3.Connection:
    conn = connect_sqlite(":memory:")
    if migrate_schema:
        migrate(conn)
    return conn


def insert_test_run_record(conn: sqlite3.Connection, run_id: str = "run_1") -> None:
    conn.execute(
        """
        INSERT INTO run_records (id, started_at, status, created_at)
        VALUES (?, '2026-07-08T00:00:00+00:00', 'running', '2026-07-08T00:00:00+00:00')
        """,
        (run_id,),
    )
    conn.commit()
