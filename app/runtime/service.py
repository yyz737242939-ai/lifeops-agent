"""Runtime service entrypoint."""

from __future__ import annotations

import logging
import json
import inspect
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.context.assembler import ContextAssembler
from app.context.budget import estimate_tokens
from app.context.errors import ContextError, ContextErrorCode
from app.context.models import (
    ContextAssembly,
    ContextBudget,
    ContextQuery,
    ContextQueryOrigin,
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.ports import ConversationRepository
from app.executor.service import ReactExecutor
from app.intent.service import IntentService
from app.observability.events import LogTraceEvent
from app.observability.file_logs import EventLogWriter, RequestLlmLog, SessionLogWriter
from app.observability.logger import (
    close_application_logging,
    OptionalLogAppender,
    configure_application_logging,
    ensure_application_logger,
)
from app.observability.logger import TraceSink
from app.observability.telemetry import (
    RequestTelemetry,
    SpanLinkInput,
    add_span_link,
)
from app.observability.trace_reader import FileTraceStore
from app.observability.trace_vocabulary import SpanLinkType, TraceStatus
from app.orchestration.graph import RuntimeOrchestrator
from app.orchestration.state import GraphRoute, GraphState
from app.planning.controller import PlanController
from app.planning.models import PlanCommand, PlanningLimits
from app.planning.ports import PlanningRouteClient
from app.planning.service import PlanningService
from app.policy.service import PolicyService
from app.recovery.finalizer import RuntimeOutcomeFinalizerPort
from app.recovery.models import RunGateOutcome
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.runtime.run_store import fail_run_record, finish_run_record, insert_run_record
from app.skills.service import SkillService
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
        execution_scope_factory: Callable[..., ToolRuntime] | None = None,
        executor: ReactExecutor | None = None,
        planning_route_client: PlanningRouteClient | None = None,
        planning_service: PlanningService | None = None,
        plan_controller: PlanController | None = None,
        planning_limits: PlanningLimits | None = None,
        conversation_repository: ConversationRepository | None = None,
        context_assembler: ContextAssembler | None = None,
        context_budget: ContextBudget | None = None,
        outcome_finalizer: RuntimeOutcomeFinalizerPort | None = None,
    ) -> None:
        self._intent_service = intent_service or IntentService()
        self._policy_service = policy_service or PolicyService()
        self._orchestrator = RuntimeOrchestrator(
            intent_service=self._intent_service,
            policy_service=self._policy_service,
            skill_service=skill_service,
            execution_scope_factory=execution_scope_factory,
            executor=executor,
            planning_route_client=planning_route_client,
            planning_service=planning_service,
            plan_controller=plan_controller,
            planning_limits=planning_limits,
        )
        self._conn = conn
        self._event_log = event_log
        self._log_root = Path(log_root) if log_root is not None else None
        self._session_logs: dict[str, SessionLogWriter] = {}
        if (conversation_repository is None) != (context_assembler is None):
            raise ValueError(
                "conversation_repository and context_assembler must be configured together."
            )
        self._conversation_repository = conversation_repository
        self._context_assembler = context_assembler
        self._context_budget = context_budget or ContextBudget(
            max_total_tokens=4000,
            max_recent_turns=8,
            max_summary_tokens=1000,
            max_profile_tokens=500,
            max_memory_items=5,
            max_memory_tokens=500,
            max_current_input_tokens=2000,
        )
        self._outcome_finalizer = outcome_finalizer
        ensure_application_logger()
        self._logger = logging.getLogger("lifeops.runtime")

    def handle(self, request: RuntimeRequest) -> RuntimeResult:
        """Run one request through authorization and direct Tool execution."""

        trace = self._build_request_telemetry(request)
        llm_log = self._build_llm_log(request, trace)

        if self._conn is None:
            try:
                self._append_request_started(request, trace)
                result = self._handle_with_context(
                    request, trace=trace, llm_log=llm_log
                )
            except Exception:
                trace.finish(
                    status=TraceStatus.ERROR,
                    error_code="runtime.orchestration_failed",
                )
                raise
            self._finish_request_telemetry(trace, result)
            return result

        insert_run_record(self._conn, request)
        self._conn.commit()
        try:
            self._append_request_started(request, trace)
            result = self._handle_with_context(
                request, trace=trace, llm_log=llm_log
            )
        except Exception:
            self._conn.rollback()
            fail_run_record(
                self._conn, request.run_id, "runtime.orchestration_failed"
            )
            self._conn.commit()
            trace.finish(
                status=TraceStatus.ERROR,
                error_code="runtime.orchestration_failed",
            )
            raise
        try:
            finish_run_record(self._conn, result)
            self._conn.commit()
            self._finish_request_telemetry(trace, result)
            return result
        except Exception:
            self._conn.rollback()
            trace.finish(
                status=TraceStatus.ERROR,
                error_code="runtime.persistence_failed",
            )
            raise

    def close(self) -> None:
        """Close the owned SQLite connection when one is attached."""

        if self._conn is not None:
            self._conn.close()
        if self._log_root is not None:
            close_application_logging()

    def handle_plan_command(
        self, command: PlanCommand, request: RuntimeRequest
    ) -> RuntimeResult:
        """Run one structured plan command with an explicit goal request."""

        trace = self._build_request_telemetry(request)
        self._add_plan_continuation(trace, command)
        llm_log = self._build_llm_log(request, trace)
        if self._conn is None:
            try:
                self._append_request_started(request, trace)
                result = self._handle_plan_command_with_context(
                    command, request, trace=trace, llm_log=llm_log
                )
            except Exception:
                trace.finish(
                    status=TraceStatus.ERROR,
                    error_code="runtime.orchestration_failed",
                )
                raise
            self._finish_request_telemetry(trace, result)
            return result

        insert_run_record(self._conn, request)
        self._conn.commit()
        try:
            self._append_request_started(request, trace)
            result = self._handle_plan_command_with_context(
                command, request, trace=trace, llm_log=llm_log
            )
            finish_run_record(self._conn, result)
            self._conn.commit()
            self._finish_request_telemetry(trace, result)
            return result
        except Exception:
            self._conn.rollback()
            fail_run_record(
                self._conn, request.run_id, "runtime.orchestration_failed"
            )
            self._conn.commit()
            trace.finish(
                status=TraceStatus.ERROR,
                error_code="runtime.orchestration_failed",
            )
            raise

    def _handle_core(
        self,
        request: RuntimeRequest,
        *,
        trace: TraceSink,
        llm_log: RequestLlmLog | None,
        context_assembly: ContextAssembly | None = None,
    ) -> RuntimeResult:
        try:
            invoke_kwargs: dict[str, Any] = {"trace": trace}
            if llm_log is not None:
                invoke_kwargs["llm_log"] = llm_log
            if context_assembly is not None:
                invoke_kwargs["context_assembly"] = context_assembly
            final_state = self._orchestrator.invoke(request, **invoke_kwargs)
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
        result = self._finalize_outcome(
            request,
            result,
            trace,
            gate_outcome=self._gate_outcome(final_state),
            plan_finalizer_output=getattr(result, "plan_finalizer_output", None),
        )

        if result.error_code is not None:
            trace.append(
                "runtime.run.failed",
                {
                    "error_code": result.error_code,
                    "stage": final_state["error_stage"],
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
            },
        )
        return result

    def _handle_with_context(
        self,
        request: RuntimeRequest,
        *,
        trace: TraceSink,
        llm_log: RequestLlmLog | None,
    ) -> RuntimeResult:
        prepared = self._prepare_context(
            request,
            turn_kind=ConversationTurnKind.NATURAL_INPUT,
            turn_content=request.user_input,
            query_text=request.user_input,
            query_origin=ContextQueryOrigin.CURRENT_USER_GOAL,
            llm_log=llm_log,
            trace=trace,
        )
        if isinstance(prepared, RuntimeResult):
            prepared = self._finalize_outcome(
                request,
                prepared,
                trace,
                gate_outcome=RunGateOutcome.NOT_RUN,
            )
            self._append_context_failure(prepared, trace)
            return prepared
        result = self._handle_core(
            request,
            trace=trace,
            llm_log=llm_log,
            context_assembly=prepared,
        )
        self._append_assistant_turn(request, result, trace=trace)
        return result

    def _handle_plan_command_core(
        self,
        command: PlanCommand,
        request: RuntimeRequest,
        *,
        trace: TraceSink,
        llm_log: RequestLlmLog | None,
        context_assembly: ContextAssembly | None = None,
    ) -> RuntimeResult:
        invoke_kwargs: dict[str, Any] = {"trace": trace}
        if llm_log is not None:
            invoke_kwargs["llm_log"] = llm_log
        if context_assembly is not None:
            invoke_kwargs["context_assembly"] = context_assembly
        final_state = self._orchestrator.invoke_plan_command(
            request,
            command,
            **invoke_kwargs,
        )
        result = final_state["result"]
        if result is None:
            raise RuntimeError("plan command completed without a result.")
        result = self._finalize_outcome(
            request,
            result,
            trace,
            gate_outcome=self._gate_outcome(final_state),
            plan_finalizer_output=getattr(result, "plan_finalizer_output", None),
        )
        if result.error_code is not None:
            trace.append(
                "runtime.run.failed",
                {"error_code": result.error_code, "stage": "planning"},
            )
        else:
            trace.append("runtime.run.completed", {"status": result.status.value})
        return result

    def _handle_plan_command_with_context(
        self,
        command: PlanCommand,
        request: RuntimeRequest,
        *,
        trace: TraceSink,
        llm_log: RequestLlmLog | None,
    ) -> RuntimeResult:
        content = json.dumps(
            {
                "action": command.action.value,
                "command_id": command.command_id,
                "feedback": command.feedback,
                "plan_id": command.plan_id,
                "revision": command.revision,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        prepared = self._prepare_context(
            request,
            turn_kind=ConversationTurnKind.PLAN_COMMAND,
            turn_content=content,
            query_text=request.user_input,
            query_origin=ContextQueryOrigin.CONFIRMED_PLAN_GOAL,
            llm_log=llm_log,
            trace=trace,
        )
        if isinstance(prepared, RuntimeResult):
            prepared = self._finalize_outcome(
                request,
                prepared,
                trace,
                gate_outcome=RunGateOutcome.NOT_RUN,
            )
            self._append_context_failure(prepared, trace)
            return prepared
        result = self._handle_plan_command_core(
            command,
            request,
            trace=trace,
            llm_log=llm_log,
            context_assembly=prepared,
        )
        self._append_assistant_turn(request, result, trace=trace)
        return result

    def _prepare_context(
        self,
        request: RuntimeRequest,
        *,
        turn_kind: ConversationTurnKind,
        turn_content: str,
        query_text: str,
        query_origin: ContextQueryOrigin,
        llm_log: RequestLlmLog | None,
        trace: TraceSink,
    ) -> ContextAssembly | RuntimeResult | None:
        if self._conversation_repository is None or self._context_assembler is None:
            return None
        if any(
            estimate_tokens(content) > self._context_budget.max_current_input_tokens
            for content in {query_text, turn_content}
        ):
            return RuntimeResult(
                request.run_id,
                request.session_id,
                RuntimeStatus.ERROR,
                "Current input is too large.",
                error_code=ContextErrorCode.INPUT_TOO_LARGE.value,
            )
        try:
            existing = self._conversation_repository.load_turns(
                request.session_id,
                None,
                None,
            )
            self._conversation_repository.append_turn(
                ConversationTurn(
                    schema_version=1,
                    session_id=request.session_id,
                    turn_id=request.turn_id,
                    sequence=len(existing) + 1,
                    role=ConversationRole.USER,
                    kind=turn_kind,
                    content=turn_content,
                    run_id=request.run_id,
                    created_at=request.created_at,
                )
            )
            trace.append(
                "context.turn.persisted",
                {
                    "role": ConversationRole.USER.value,
                    "kind": turn_kind.value,
                    "sequence": len(existing) + 1,
                },
            )
            assembly = self._context_assembler.assemble(
                ContextQuery(
                    text=query_text,
                    origin=query_origin,
                    session_id=request.session_id,
                    run_id=request.run_id,
                    turn_id=request.turn_id,
                ),
                self._context_budget,
                llm_log=llm_log,
            )
            trace.append(
                "context.assembled",
                self._context_report_payload(assembly),
            )
            return assembly
        except ContextError as exc:
            return RuntimeResult(
                request.run_id,
                request.session_id,
                RuntimeStatus.ERROR,
                "Context preparation failed.",
                error_code=exc.code or ContextErrorCode.ASSEMBLY_FAILED.value,
            )

    def _append_assistant_turn(
        self,
        request: RuntimeRequest,
        result: RuntimeResult,
        *,
        trace: TraceSink,
    ) -> None:
        """Persist only the user-visible RuntimeResult after orchestration completes."""

        if self._conversation_repository is None:
            return
        result_type = None
        if result.tool_result is not None:
            candidate_type = result.tool_result.get("type")
            if isinstance(candidate_type, str):
                result_type = candidate_type
        kind = {
            "planning_clarification": ConversationTurnKind.CLARIFICATION,
            "plan_preview": ConversationTurnKind.PLAN_PREVIEW,
            "plan_result": ConversationTurnKind.COMMAND_RESULT,
        }.get(result_type, ConversationTurnKind.FINAL_ANSWER)
        content = result.message
        if result.tool_result is not None:
            content = json.dumps(
                {
                    "message": result.message,
                    "tool_result": result.tool_result,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        try:
            existing = self._conversation_repository.load_turns(
                request.session_id,
                None,
                None,
            )
            self._conversation_repository.append_turn(
                ConversationTurn(
                    schema_version=1,
                    session_id=request.session_id,
                    turn_id=new_id("turn"),
                    sequence=len(existing) + 1,
                    role=ConversationRole.ASSISTANT,
                    kind=kind,
                    content=content,
                    run_id=request.run_id,
                    created_at=utc_now_iso(),
                )
            )
            trace.append(
                "context.turn.persisted",
                {
                    "role": ConversationRole.ASSISTANT.value,
                    "kind": kind.value,
                    "sequence": len(existing) + 1,
                },
            )
        except ContextError as exc:
            error_code = exc.code or ContextErrorCode.CONVERSATION_PERSIST_FAILED.value
            trace.append(
                "context.conversation.persist_failed",
                {
                    "component": "assistant_persistence",
                    "error_code": error_code,
                },
            )
            self._logger.error(
                "assistant turn persistence failed run_id=%s error_code=%s",
                request.run_id,
                error_code,
            )

    def _finalize_outcome(
        self,
        request: RuntimeRequest,
        draft: RuntimeResult,
        trace: TraceSink,
        *,
        gate_outcome: RunGateOutcome | None,
        plan_finalizer_output=None,
    ) -> RuntimeResult:
        if self._outcome_finalizer is None:
            if type(draft) is RuntimeResult:
                return draft
            return RuntimeResult(
                draft.run_id,
                draft.session_id,
                draft.status,
                draft.message,
                draft.tool_result,
                draft.error_code,
            )
        trace_context = getattr(trace, "trace_context", None)
        trace_id = getattr(trace_context, "trace_id", None)
        if not isinstance(trace_id, str) or not trace_id:
            return draft
        return _invoke_outcome_finalizer(
            self._outcome_finalizer,
            request,
            draft,
            trace_id=trace_id,
            trace=trace,
            gate_outcome=gate_outcome,
            plan_finalizer_output=plan_finalizer_output,
        )

    @staticmethod
    def _gate_outcome(state: GraphState) -> RunGateOutcome | None:
        if state.get("route") is GraphRoute.DENY:
            return RunGateOutcome.DENIED
        if state.get("route") is GraphRoute.REQUIRES_CONFIRMATION:
            return RunGateOutcome.REQUIRES_CONFIRMATION
        result = state.get("result")
        if result is not None and result.error_code is not None:
            return RunGateOutcome.NOT_RUN
        return None

    @staticmethod
    def _context_report_payload(assembly: ContextAssembly) -> dict[str, Any]:
        report = assembly.report
        return {
            "assembly_id": report.assembly_id,
            "estimated_total_tokens": assembly.estimated_total_tokens,
            "selected_turn_count": report.selected_turn_count,
            "summary_version": report.summary_version,
            "summary_covered_range": (
                list(report.summary_covered_range)
                if report.summary_covered_range is not None
                else None
            ),
            "profile_included": report.profile_included,
            "memory_candidate_count": report.memory_candidate_count,
            "memory_selected_count": report.memory_selected_count,
            "per_kind_estimated_tokens": {
                item.kind.value: item.estimated_tokens
                for item in report.per_kind_estimated_tokens
            },
            "trimmed_counts": {
                item.kind.value: item.count for item in report.trimmed_counts
            },
            "degradations": [
                {
                    "component": item.component.value,
                    "error_code": item.error_code.value,
                }
                for item in report.degradations
            ],
        }

    @staticmethod
    def _append_context_failure(
        result: RuntimeResult,
        trace: TraceSink,
    ) -> None:
        trace.append(
            "runtime.run.failed",
            {"error_code": result.error_code, "stage": "context"},
        )

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

    def _build_request_telemetry(self, request: RuntimeRequest) -> RequestTelemetry:
        session_log = (
            self._ensure_session_log(request) if self._log_root is not None else None
        )
        return RequestTelemetry(
            run_id=request.run_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            legacy_sink=OptionalLogAppender(self._build_event_appender(request)),
            exporter=session_log.trace_exporter if session_log is not None else None,
            annotation_sink=session_log.annotation_sink if session_log is not None else None,
        )

    def _build_llm_log(
        self, request: RuntimeRequest, telemetry: RequestTelemetry
    ) -> RequestLlmLog | None:
        if self._log_root is None:
            return None
        return RequestLlmLog(
            self._ensure_session_log(request).llm_log, request, telemetry
        )

    def _add_plan_continuation(
        self,
        telemetry: RequestTelemetry,
        command: PlanCommand,
    ) -> None:
        if self._log_root is None or command.plan_id is None:
            return
        try:
            preview_trace_id = FileTraceStore(
                self._log_root
            ).find_plan_preview_trace_id(command.plan_id)
            if preview_trace_id is None:
                return
            add_span_link(
                telemetry,
                SpanLinkInput(
                    target_trace_id=preview_trace_id,
                    link_type=SpanLinkType.PLAN_CONTINUATION,
                    attributes={
                        "lifeops.plan.id": command.plan_id,
                        "lifeops.plan.revision": command.revision,
                    },
                ),
            )
        except Exception:
            self._logger.error(
                "plan continuation trace lookup failed plan_id=%s",
                command.plan_id,
            )

    @staticmethod
    def _finish_request_telemetry(
        telemetry: RequestTelemetry, result: RuntimeResult
    ) -> None:
        telemetry.finish(
            status=TraceStatus.ERROR if result.error_code else TraceStatus.OK,
            error_code=result.error_code,
        )

    def _append_request_started(
        self,
        request: RuntimeRequest,
        trace: TraceSink,
    ) -> None:
        trace.append("runtime.run.started")

    def _ensure_session_log(self, request: RuntimeRequest) -> SessionLogWriter:
        existing = self._session_logs.get(request.session_id)
        if existing is not None:
            configure_application_logging(existing.session_dir)
            return existing
        if self._log_root is None:
            raise RuntimeError("log_root is not configured.")
        session_log = SessionLogWriter.create(
            self._log_root,
            session_id=request.session_id,
            metadata={"first_run_id": request.run_id},
        )
        configure_application_logging(session_log.session_dir)
        self._session_logs[request.session_id] = session_log
        return session_log


def _invoke_outcome_finalizer(finalizer, request, draft, **context):
    """Pass additive finalizer context without breaking older implementations."""

    method = finalizer.finalize
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return method(request, draft, **context)
    accepts_extra = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    accepted_names = {parameter.name for parameter in parameters}
    selected = (
        context
        if accepts_extra
        else {name: value for name, value in context.items() if name in accepted_names}
    )
    return method(request, draft, **selected)
