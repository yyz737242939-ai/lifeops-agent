"""Runtime service entrypoint."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.intent.models import IntentDecision
from app.intent.service import IntentService
from app.observability.events import LogTraceEvent
from app.observability.trace_store import LogTraceStore
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
    ) -> None:
        self._intent_service = intent_service or IntentService()
        self._policy_service = policy_service or PolicyService()
        self._conn = conn
        self._trace_store = LogTraceStore(conn) if conn is not None else None

    def handle(self, request: RuntimeRequest) -> RuntimeResult:
        """Run one request through Intent and Policy without executing tools yet."""

        if self._conn is None or self._trace_store is None:
            return self._handle_core(request)

        seq = 0

        def append_trace(event_type: str, payload: dict[str, Any] | None = None) -> None:
            nonlocal seq
            seq += 1
            self._trace_store.append_event(
                LogTraceEvent(
                    run_id=request.run_id,
                    seq=seq,
                    event_type=event_type,
                    payload=payload or {},
                )
            )

        with SqliteUnitOfWork(self._conn):
            insert_run_record(self._conn, request)
            append_trace("runtime.run.started")
            append_trace(
                "runtime.request.created",
                {
                    "session_id": request.session_id,
                    "turn_id": request.turn_id,
                },
            )
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
        append_trace: Any | None = None,
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
        return result


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
