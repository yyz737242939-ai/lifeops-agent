"""Minimal restart-safe runtime for explicit read-only Recovery requests."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.common.config import load_app_config
from app.common.errors import AppError
from app.common.ids import new_id
from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry
from app.observability.trace_vocabulary import TraceStatus
from app.recovery.models import RecoveryResult
from app.recovery.errors import RECOVERY_EXPLAINER_FAILED
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.recovery.service import RecoveryService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


class RecoveryRuntime:
    """Own durable reads and a fresh Recovery trace, with no execution wiring."""

    def __init__(self, conn: sqlite3.Connection, log_root: str | Path) -> None:
        self._conn = conn
        self._log_root = Path(log_root)
        self._service = RecoveryService(SqliteExecutionFeedbackRepository(conn))

    def explain(self, session_id: str, run_id: str | None = None) -> RecoveryResult:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", session_id) is None:
            raise ValueError("session_id must be a path-safe stable identifier.")
        recovery_run_id = new_id("recovery_run")
        logs = SessionLogWriter.create(self._log_root, session_id=session_id)
        telemetry = RequestTelemetry(
            run_id=recovery_run_id,
            session_id=session_id,
            turn_id=new_id("turn"),
            legacy_sink=OptionalLogAppender(None),
            exporter=logs.trace_exporter,
        )
        try:
            result = self._service.explain_run(
                session_id,
                run_id,
                trace=telemetry,
            )
        except AppError as exc:
            telemetry.finish(status=TraceStatus.ERROR, error_code=exc.code)
            raise
        except Exception:
            telemetry.finish(
                status=TraceStatus.ERROR,
                error_code=RECOVERY_EXPLAINER_FAILED,
            )
            raise
        telemetry.finish(status=TraceStatus.OK)
        return result

    def close(self) -> None:
        self._conn.close()


def build_recovery_runtime(
    config_path: str | Path = "config/default.json",
) -> RecoveryRuntime:
    config = load_app_config(config_path)
    conn = connect_sqlite(config.database_path)
    migrate(conn)
    return RecoveryRuntime(conn, config.log_root)
