from __future__ import annotations

import sqlite3
from typing import Any

from app.runtime.models import RuntimeRequest
from app.tools.models import ConfirmedAction, ToolCall
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
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


def create_test_skill_service() -> SkillService:
    return SkillService(SkillRegistry(), _NoSkillSelectionClient())


def confirmed_action(
    call: ToolCall, *, run_id: str = "run_test"
) -> ConfirmedAction:
    return ConfirmedAction.for_call(
        run_id,
        call,
        expires_at="2099-01-01T00:00:00+00:00",
    )


class _NoSkillSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        return {"selected_skill_ids": [], "reason": "No test Skill applies."}
