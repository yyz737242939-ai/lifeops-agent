"""SQLite helpers for runtime run records."""

from __future__ import annotations

import hashlib
import sqlite3

from app.common.time import utc_now_iso
from app.runtime.models import RuntimeRequest, RuntimeResult


def insert_run_record(conn: sqlite3.Connection, request: RuntimeRequest) -> None:
    """Create the durable run evidence row for one runtime request."""

    conn.execute(
        """
        INSERT INTO run_records (id, started_at, status, user_input_hash, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            request.run_id,
            request.created_at,
            "running",
            _hash_user_input(request.user_input),
            request.created_at,
        ),
    )


def finish_run_record(conn: sqlite3.Connection, result: RuntimeResult) -> None:
    """Update the durable run evidence row after handling completes."""

    conn.execute(
        """
        UPDATE run_records
        SET finished_at = ?, status = ?, summary = ?, error_code = ?
        WHERE id = ?
        """,
        (
            utc_now_iso(),
            result.status.value,
            result.message,
            result.error_code,
            result.run_id,
        ),
    )


def _hash_user_input(user_input: str) -> str:
    return hashlib.sha256(user_input.encode("utf-8")).hexdigest()
