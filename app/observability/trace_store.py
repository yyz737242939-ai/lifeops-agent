"""Store for structured runtime trace events."""

from __future__ import annotations

import sqlite3

from app.common.serialization import from_json, to_json
from app.observability.events import LogTraceEvent


class LogTraceStore:
    """SQLite-backed store for compact runtime trace logs."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def append_event(self, event: LogTraceEvent) -> LogTraceEvent:
        self.conn.execute(
            """
            INSERT INTO trace_events (id, run_id, seq, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.run_id,
                event.seq,
                event.event_type,
                to_json(event.payload),
                event.created_at,
            ),
        )
        return event

    def list_events(self, run_id: str) -> list[LogTraceEvent]:
        rows = self.conn.execute(
            """
            SELECT id, run_id, seq, event_type, payload_json, created_at
            FROM trace_events
            WHERE run_id = ?
            ORDER BY seq ASC
            """,
            (run_id,),
        ).fetchall()

        return [
            LogTraceEvent(
                id=row["id"],
                run_id=row["run_id"],
                seq=row["seq"],
                event_type=row["event_type"],
                payload=from_json(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
