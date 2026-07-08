"""Store for raw LLM and agent request-response records."""

from __future__ import annotations

import sqlite3

from app.common.serialization import from_json, to_json
from app.observability.events import LogLlmInteraction


class LogLlmInteractionStore:
    """SQLite-backed store for raw LLM request-response logs."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def append_interaction(self, interaction: LogLlmInteraction) -> LogLlmInteraction:
        self.conn.execute(
            """
            INSERT INTO llm_interactions (
                id,
                run_id,
                seq,
                provider,
                model,
                request_json,
                response_json,
                status,
                error_code,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.id,
                interaction.run_id,
                interaction.seq,
                interaction.provider,
                interaction.model,
                to_json(interaction.request),
                to_json(interaction.response) if interaction.response is not None else None,
                interaction.status,
                interaction.error_code,
                interaction.created_at,
            ),
        )
        return interaction

    def list_interactions(self, run_id: str) -> list[LogLlmInteraction]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                run_id,
                seq,
                provider,
                model,
                request_json,
                response_json,
                status,
                error_code,
                created_at
            FROM llm_interactions
            WHERE run_id = ?
            ORDER BY seq ASC
            """,
            (run_id,),
        ).fetchall()

        return [
            LogLlmInteraction(
                id=row["id"],
                run_id=row["run_id"],
                seq=row["seq"],
                provider=row["provider"],
                model=row["model"],
                request=from_json(row["request_json"]),
                response=from_json(row["response_json"]) if row["response_json"] is not None else None,
                status=row["status"],
                error_code=row["error_code"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
