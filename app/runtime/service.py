"""Runtime service entrypoint."""

from __future__ import annotations

import sqlite3
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.intent.models import IntentDecision
from app.intent.service import IntentService
from app.observability.events import LogTraceEvent
from app.observability.file_logs import EventLogWriter, SessionLogWriter
from app.observability.logger import configure_application_logging, ensure_application_logger
from app.policy.models import PolicyAction, PolicyDecision
from app.policy.service import PolicyService
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.runtime.run_store import finish_run_record, insert_run_record
from app.storage.unit_of_work import SqliteUnitOfWork


class RuntimeService:
    """Coordinates the request-local runtime chain."""

    def __init__(
        self,
        intent_service: IntentService | None = None,
        policy_service: PolicyService | None = None,
        conn: sqlite3.Connection | None = None,
        event_log: EventLogWriter | None = None,
        log_root: str | Path | None = None,
    ) -> None:
        self._intent_service = intent_service or IntentService()
        self._policy_service = policy_service or PolicyService()
        self._conn = conn
        self._event_log = event_log
        self._log_root = Path(log_root) if log_root is not None else None
        self._session_log: SessionLogWriter | None = None
        ensure_application_logger()
        self._logger = logging.getLogger("lifeops.runtime")

    def handle(self, request: RuntimeRequest) -> RuntimeResult:
        """Run one request through Intent and Policy without executing tools yet."""

        append_trace = self._build_event_appender(request)

        if self._conn is None:
            if append_trace is not None:
                append_trace("runtime.run.started")
                append_trace(
                    "runtime.request.created",
                    {
                        "session_id": request.session_id,
                        "turn_id": request.turn_id,
                    },
                )
            self._logger.info("runtime run started run_id=%s", request.run_id)
            return self._handle_core(request, append_trace=append_trace)

        with SqliteUnitOfWork(self._conn):
            insert_run_record(self._conn, request)
            if append_trace is not None:
                append_trace("runtime.run.started")
                append_trace(
                    "runtime.request.created",
                    {
                        "session_id": request.session_id,
                        "turn_id": request.turn_id,
                    },
                )
            self._logger.info("runtime run started run_id=%s", request.run_id)
            result = self._handle_core(request, append_trace=append_trace)
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
        append_trace: Callable[[str, dict[str, Any] | None], None] | None = None,
    ) -> RuntimeResult:
        try:
            if append_trace is not None:
                append_trace("runtime.intent.started")
            intent = self._intent_service.classify(request)
            if append_trace is not None:
                append_trace("runtime.intent.completed", _intent_summary(intent))
        except Exception as exc:
            result = RuntimeResult(
                run_id=request.run_id,
                session_id=request.session_id,
                status=RuntimeStatus.ERROR,
                message="Intent classification failed.",
                error_code="runtime.intent_failed",
                trace_summary=[_safe_error_summary(exc)],
            )
            if append_trace is not None:
                append_trace(
                    "runtime.run.failed",
                    {"error_code": result.error_code, "stage": "intent"},
                )
            self._logger.exception("runtime run failed run_id=%s stage=intent", request.run_id)
            return result

        try:
            if append_trace is not None:
                append_trace("runtime.policy.started")
            policy = self._policy_service.evaluate(request, intent)
            if append_trace is not None:
                append_trace("runtime.policy.completed", _policy_summary(policy))
        except Exception as exc:
            result = RuntimeResult(
                run_id=request.run_id,
                session_id=request.session_id,
                status=RuntimeStatus.ERROR,
                message="Policy evaluation failed.",
                intent=_intent_summary(intent),
                error_code="runtime.policy_failed",
                trace_summary=[_safe_error_summary(exc)],
            )
            if append_trace is not None:
                append_trace(
                    "runtime.run.failed",
                    {"error_code": result.error_code, "stage": "policy"},
                )
            self._logger.exception("runtime run failed run_id=%s stage=policy", request.run_id)
            return result

        result = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=_status_from_policy(policy),
            message=_message_from_policy(policy),
            intent=_intent_summary(intent),
            policy=_policy_summary(policy),
            trace_summary=["runtime.orchestration.stubbed"],
        )
        if append_trace is not None:
            append_trace(
                "runtime.orchestration.stubbed",
                {"status": result.status.value},
            )
            append_trace(
                "runtime.run.completed",
                {"status": result.status.value},
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


def _status_from_policy(policy: PolicyDecision) -> RuntimeStatus:
    if policy.action == PolicyAction.ALLOW:
        return RuntimeStatus.OK
    if policy.action == PolicyAction.REQUIRES_CONFIRMATION:
        return RuntimeStatus.REQUIRES_CONFIRMATION
    return RuntimeStatus.UNSUPPORTED


def _message_from_policy(policy: PolicyDecision) -> str:
    if policy.action == PolicyAction.ALLOW:
        return "Request passed intent and policy checks; execution is not implemented yet."
    if policy.action == PolicyAction.REQUIRES_CONFIRMATION:
        return "Request requires confirmation before execution."
    return "Request is not allowed by policy."


def _intent_summary(intent: IntentDecision) -> dict[str, Any]:
    return {
        "intent_type": intent.intent_type.value,
        "confidence": intent.confidence,
        "needs_clarification": intent.needs_clarification,
        "write_candidate": intent.write_candidate,
        "classifier_results": [
            {
                "classifier_name": result.classifier_name,
                "status": result.status,
                "intent_type": result.intent_type.value,
                "confidence": result.confidence,
            }
            for result in intent.classifier_results
        ],
    }


def _policy_summary(policy: PolicyDecision) -> dict[str, Any]:
    return {
        "action": policy.action.value,
        "authorized_write_scopes": [
            scope.value for scope in policy.authorized_write_scopes
        ],
        "allowed_tools": policy.allowed_tools,
        "requires_confirmation": policy.requires_confirmation,
        "denied_reason": policy.denied_reason,
    }


def _safe_error_summary(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"
