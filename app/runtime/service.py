"""Runtime service entrypoint."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.intent.service import IntentService
from app.observability.events import LogTraceEvent
from app.observability.file_logs import EventLogWriter, SessionLogWriter
from app.observability.logger import (
    OptionalLogAppender,
    configure_application_logging,
    ensure_application_logger,
)
from app.orchestration.graph import RuntimeOrchestrator
from app.policy.service import PolicyService
from app.runtime.models import RuntimeRequest, RuntimeResult
from app.runtime.run_store import finish_run_record, insert_run_record
from app.storage.unit_of_work import SqliteUnitOfWork
from app.skills.service import SkillService
from app.tools.calling import ToolCallSelectionClient
from app.tools.runtime import ToolRuntime


class RuntimeService:
    """Coordinates the request-local runtime chain."""

    def __init__(
        self,
        skill_service: SkillService,
        intent_service: IntentService | None = None,
        policy_service: PolicyService | None = None,
        conn: sqlite3.Connection | None = None,
        event_log: EventLogWriter | None = None,
        log_root: str | Path | None = None,
        tool_runtime_factory: Callable[[], ToolRuntime] | None = None,
        tool_call_selection_client: ToolCallSelectionClient | None = None,
    ) -> None:
        self._intent_service = intent_service or IntentService()
        self._policy_service = policy_service or PolicyService()
        self._orchestrator = RuntimeOrchestrator(
            intent_service=self._intent_service,
            policy_service=self._policy_service,
            skill_service=skill_service,
            tool_runtime_factory=tool_runtime_factory,
            tool_call_selection_client=tool_call_selection_client,
        )
        self._conn = conn
        self._event_log = event_log
        self._log_root = Path(log_root) if log_root is not None else None
        self._session_log: SessionLogWriter | None = None
        ensure_application_logger()
        self._logger = logging.getLogger("lifeops.runtime")

    def handle(self, request: RuntimeRequest) -> RuntimeResult:
        """Run one request through authorization and direct Tool execution."""

        trace = OptionalLogAppender(self._build_event_appender(request))

        if self._conn is None:
            self._append_request_started(request, trace)
            self._logger.info("runtime run started run_id=%s", request.run_id)
            return self._handle_core(request, trace=trace)

        with SqliteUnitOfWork(self._conn):
            insert_run_record(self._conn, request)
            self._append_request_started(request, trace)
            self._logger.info("runtime run started run_id=%s", request.run_id)
            result = self._handle_core(request, trace=trace)
            finish_run_record(self._conn, result)
            return result

    def close(self) -> None:
        """Close the owned SQLite connection when one is attached."""

        if self._conn is not None:
            self._conn.close()

    def _handle_core(
        self,
        request: RuntimeRequest,
        *,
        trace: OptionalLogAppender,
    ) -> RuntimeResult:
        try:
            final_state = self._orchestrator.invoke(request, trace=trace)
        except Exception as exc:
            trace.append(
                "runtime.run.failed",
                {
                    "error_code": "runtime.orchestration_failed",
                    "stage": "orchestration",
                    "error_type": exc.__class__.__name__,
                },
            )
            self._logger.exception(
                "runtime run failed run_id=%s stage=orchestration",
                request.run_id,
            )
            raise

        result = final_state["result"]
        if result is None:
            raise RuntimeError("runtime graph completed without a result.")

        if result.error_code is not None:
            trace.append(
                "runtime.run.failed",
                {
                    "error_code": result.error_code,
                    "stage": final_state["error_stage"],
                    "graph_path": list(final_state["graph_path"]),
                },
            )
            self._logger.error(
                "runtime run failed run_id=%s stage=%s error_code=%s",
                request.run_id,
                final_state["error_stage"],
                result.error_code,
            )
            return result

        trace.append(
            "runtime.run.completed",
            {
                "status": result.status.value,
                "graph_path": list(final_state["graph_path"]),
            },
        )
        self._logger.info(
            "runtime run completed run_id=%s status=%s",
            request.run_id,
            result.status.value,
        )
        return result

    def _build_event_appender(
        self,
        request: RuntimeRequest,
    ) -> Callable[[str, dict[str, Any] | None], None] | None:
        event_log = self._event_log
        if event_log is None and self._log_root is not None:
            event_log = self._ensure_session_log(request).event_log
        if event_log is None:
            return None

        seq = 0

        def append_trace(event_type: str, payload: dict[str, Any] | None = None) -> None:
            nonlocal seq
            seq += 1
            event_log.append(
                LogTraceEvent(
                    run_id=request.run_id,
                    seq=seq,
                    event_type=event_type,
                    payload=payload or {},
                    session_id=request.session_id,
                    turn_id=request.turn_id,
                )
            )

        return append_trace

    def _append_request_started(
        self,
        request: RuntimeRequest,
        trace: OptionalLogAppender,
    ) -> None:
        trace.append("runtime.run.started")
        trace.append(
            "runtime.request.created",
            {
                "session_id": request.session_id,
                "turn_id": request.turn_id,
            },
        )

    def _ensure_session_log(self, request: RuntimeRequest) -> SessionLogWriter:
        if self._session_log is not None:
            return self._session_log
        if self._log_root is None:
            raise RuntimeError("log_root is not configured.")
        self._session_log = SessionLogWriter.create(
            self._log_root,
            session_id=request.session_id,
            metadata={"first_run_id": request.run_id},
        )
        configure_application_logging(self._session_log.session_dir)
        return self._session_log
