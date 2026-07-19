"""Single run-level boundary for validated, durable ExecutionFeedback."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.planning.models import PlanFinalizerOutput, PlanStep, PlanStepStatus
from app.planning.ports import PlanRepository
from app.observability.logger import TraceSink
from app.observability.recovery_trace import record_execution_feedback_reference
from app.observability.telemetry import add_span_event, optional_span
from app.observability.trace_vocabulary import LifeOpsSpanKind
from app.recovery.builder import (
    DirectExecutionFacts,
    ExecutionFeedbackBuilder,
    PlanExecutorInvocationFacts,
    PlanningExecutionFacts,
    ToolEffectBinding,
)
from app.recovery.collector import (
    CollectedExecutionFacts,
    RequestExecutionFeedbackCollector,
)
from app.recovery.errors import ExecutionFeedbackCollectionError
from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    ExecutionClaim,
    ExecutionClaimKind,
    ExecutionFeedback,
    FinalAnswerDraft,
    FinalAnswerValidation,
    RunGateOutcome,
)
from app.recovery.ports import ExecutionFeedbackRepository
from app.recovery.validator import (
    VALIDATOR_FAILED,
    FinalAnswerValidator,
    deterministic_execution_fallback,
    draft_from_plan_finalizer,
)
from app.runtime.models import RuntimeRequest, RuntimeResult


SAFE_UNAVAILABLE_MESSAGE = (
    "Execution feedback is unavailable; no execution success was verified."
)


class RuntimeOutcomeFinalizerPort(Protocol):
    def finalize(
        self,
        request: RuntimeRequest,
        draft: RuntimeResult,
        *,
        trace_id: str,
        trace: TraceSink | None = None,
        gate_outcome: RunGateOutcome | None = None,
        plan_finalizer_output: PlanFinalizerOutput | None = None,
    ) -> RuntimeResult: ...


class RuntimeOutcomeFinalizer:
    """Build, validate and save exactly one run-level safe outcome."""

    def __init__(
        self,
        collector: RequestExecutionFeedbackCollector,
        repository: ExecutionFeedbackRepository,
        *,
        plan_repository: PlanRepository | None = None,
        builder: ExecutionFeedbackBuilder | None = None,
        validator: FinalAnswerValidator | None = None,
    ) -> None:
        self._collector = collector
        self._repository = repository
        self._plan_repository = plan_repository
        self._builder = builder or ExecutionFeedbackBuilder()
        self._validator = validator or FinalAnswerValidator()

    def finalize(
        self,
        request: RuntimeRequest,
        draft: RuntimeResult,
        *,
        trace_id: str,
        trace: TraceSink | None = None,
        gate_outcome: RunGateOutcome | None = None,
        plan_finalizer_output: PlanFinalizerOutput | None = None,
    ) -> RuntimeResult:
        if not isinstance(request, RuntimeRequest):
            raise ValueError("request must be a RuntimeRequest.")
        if not isinstance(draft, RuntimeResult):
            raise ValueError("draft must be a RuntimeResult.")
        if draft.run_id != request.run_id or draft.session_id != request.session_id:
            raise ValueError("draft must belong to request.")
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise ValueError("trace_id must be non-empty.")
        if gate_outcome is not None and not isinstance(gate_outcome, RunGateOutcome):
            raise ValueError("gate_outcome must be RunGateOutcome when provided.")

        with optional_span(
            trace,
            name="execution.feedback.finalize",
            kind=LifeOpsSpanKind.RUNTIME,
            attributes={"lifeops.runtime.run_id": request.run_id},
        ) as span:
            return self._finalize_current(
                request,
                draft,
                trace_id=trace_id,
                trace=trace,
                span=span,
                gate_outcome=gate_outcome,
                plan_finalizer_output=plan_finalizer_output,
            )

    def _finalize_current(
        self,
        request: RuntimeRequest,
        draft: RuntimeResult,
        *,
        trace_id: str,
        trace: TraceSink | None,
        span,
        gate_outcome: RunGateOutcome | None,
        plan_finalizer_output: PlanFinalizerOutput | None,
    ) -> RuntimeResult:
        feedback: ExecutionFeedback | None = None
        try:
            if _is_planning_result(draft):
                feedback = self._build_planning(request, draft, trace_id)
                answer_draft = (
                    draft_from_plan_finalizer(plan_finalizer_output, feedback)
                    if plan_finalizer_output is not None
                    else FinalAnswerDraft(draft.message)
                )
            else:
                feedback, answer_draft = self._build_direct(
                    request,
                    trace_id,
                    gate_outcome=gate_outcome,
                )
                answer_draft = replace(answer_draft, message=draft.message)
            add_span_event(trace, "execution.feedback.built", _feedback_attributes(feedback))
            validated = self._validator.validate(answer_draft, feedback)
            finalized = replace(feedback, validation=validated.validation)
            is_fallback = (
                validated.validation.output_mode
                is AnswerOutputMode.DETERMINISTIC_FALLBACK
            )
            add_span_event(
                trace,
                (
                    "execution.final_answer.fallback"
                    if is_fallback
                    else "execution.final_answer.validated"
                ),
                {
                    "run_id": feedback.run_id,
                    "claim_status": validated.validation.claim_status.value,
                    "answer_mode": validated.validation.output_mode.value,
                    "reason_count": len(validated.validation.reason_codes),
                    "fallback": is_fallback,
                },
            )
            persisted = self._save_best_effort(finalized)
            _record_persistence_projection(trace, finalized, persisted)
            span.set_attributes(
                {
                    "lifeops.feedback.path": feedback.path.value,
                    "lifeops.feedback.status": feedback.overall_status.value,
                    "lifeops.feedback.validation": validated.validation.claim_status.value,
                    "lifeops.feedback.persisted": persisted,
                }
            )
            return _public_result(draft, validated.message)
        except Exception as exc:
            if feedback is None:
                error_code = getattr(exc, "code", None) or "execution_feedback_source_incomplete"
                span.fail(error_code)
                add_span_event(
                    trace,
                    "execution.feedback.failed",
                    {"run_id": request.run_id, "error_code": error_code},
                )
                return _public_result(draft, SAFE_UNAVAILABLE_MESSAGE)
            validation = FinalAnswerValidation(
                ClaimStatus.INVALID,
                AnswerOutputMode.DETERMINISTIC_FALLBACK,
                (VALIDATOR_FAILED,),
            )
            finalized = replace(feedback, validation=validation)
            persisted = self._save_best_effort(finalized)
            add_span_event(
                trace,
                "execution.final_answer.fallback",
                {
                    "run_id": feedback.run_id,
                    "claim_status": ClaimStatus.INVALID.value,
                    "answer_mode": AnswerOutputMode.DETERMINISTIC_FALLBACK.value,
                    "reason_count": 1,
                    "fallback": True,
                },
            )
            _record_persistence_projection(trace, finalized, persisted)
            span.set_attributes(
                {
                    "lifeops.feedback.path": feedback.path.value,
                    "lifeops.feedback.status": feedback.overall_status.value,
                    "lifeops.feedback.validation": ClaimStatus.INVALID.value,
                    "lifeops.feedback.persisted": persisted,
                }
            )
            return _public_result(
                draft, deterministic_execution_fallback(feedback)
            )
        finally:
            self._collector.discard(request.run_id)

    def _build_direct(
        self,
        request: RuntimeRequest,
        trace_id: str,
        *,
        gate_outcome: RunGateOutcome | None,
    ) -> tuple[ExecutionFeedback, FinalAnswerDraft]:
        collected = _snapshot_optional(self._collector, request.run_id)
        if collected is None:
            if gate_outcome is None:
                raise ExecutionFeedbackCollectionError(
                    "Direct execution facts are unavailable.",
                    code="execution_feedback_source_incomplete",
                )
            return (
                self._builder.from_direct(DirectExecutionFacts(
                    new_id("feedback"),
                    trace_id,
                    request.run_id,
                    request.session_id,
                    "Direct runtime request.",
                    utc_now_iso(),
                    gate_outcome=gate_outcome,
                )),
                FinalAnswerDraft("No execution action was performed."),
            )
        if len(collected.invocations) != 1:
            raise ExecutionFeedbackCollectionError(
                "Direct execution must contain one Executor invocation.",
                code="execution_feedback_source_conflict",
            )
        invocation = collected.invocations[0]
        if invocation.plan_step is not None:
            raise ExecutionFeedbackCollectionError(
                "Direct execution contains Planning identity.",
                code="execution_feedback_source_conflict",
            )
        feedback = self._builder.from_direct(
            DirectExecutionFacts(
                new_id("feedback"),
                trace_id,
                request.run_id,
                request.session_id,
                "Direct runtime request.",
                utc_now_iso(),
                invocation.result,
                invocation.executor_invocation_id,
                invocation.source_span_id,
                tool_effects=invocation.tool_effects,
            )
        )
        claims = tuple(
            ExecutionClaim(
                claim_id=item.claim_id,
                kind=ExecutionClaimKind.ACTION_SUCCESS,
                source_run_id=request.run_id,
                session_id=request.session_id,
                call_id=item.call_id,
                evidence_refs=item.evidence_refs,
            )
            for item in invocation.result.final_answer_claims
        )
        return feedback, FinalAnswerDraft(
            invocation.result.final_message or "Execution completed.",
            claims,
        )

    def _build_planning(
        self,
        request: RuntimeRequest,
        draft: RuntimeResult,
        trace_id: str,
    ) -> ExecutionFeedback:
        if self._plan_repository is None:
            raise ExecutionFeedbackCollectionError(
                "Planning feedback requires a Plan repository.",
                code="execution_feedback_source_incomplete",
            )
        plan_id, revision = _plan_identity(draft)
        run, current_steps = self._plan_repository.get_plan(
            request.session_id, plan_id
        )
        if run.current_revision != revision:
            raise ExecutionFeedbackCollectionError(
                "Runtime Plan revision conflicts with durable PlanRun.",
                code="execution_feedback_source_conflict",
            )
        completed = self._plan_repository.list_completed_steps(plan_id, revision)
        steps = _merge_plan_steps(completed, current_steps)
        collected = _snapshot_optional(self._collector, request.run_id)
        invocations: tuple[PlanExecutorInvocationFacts, ...] = ()
        effects: tuple[ToolEffectBinding, ...] = ()
        if collected is not None:
            invocations = tuple(
                _plan_invocation(item, plan_id)
                for item in collected.invocations
            )
            effects = _merge_effects(collected)
        elif any(_step_was_executed(item) for item in steps):
            raise ExecutionFeedbackCollectionError(
                "Executed PlanSteps are missing Executor facts.",
                code="execution_feedback_source_incomplete",
            )
        return self._builder.from_plan(
            PlanningExecutionFacts(
                new_id("feedback"),
                trace_id,
                request.run_id,
                request.session_id,
                f"Planning run {plan_id}.",
                utc_now_iso(),
                run,
                steps,
                invocations,
                effects,
            )
        )

    def _save_best_effort(self, feedback: ExecutionFeedback) -> bool:
        try:
            self._repository.save(feedback)
            return True
        except Exception:
            return False


def _snapshot_optional(
    collector: RequestExecutionFeedbackCollector, run_id: str
) -> CollectedExecutionFacts | None:
    try:
        return collector.snapshot(run_id)
    except ExecutionFeedbackCollectionError as exc:
        if exc.code == "execution_feedback_source_incomplete":
            return None
        raise


def _is_planning_result(draft: RuntimeResult) -> bool:
    if draft.tool_result is None:
        return False
    return draft.tool_result.get("type") in {"plan_preview", "plan_result"}


def _plan_identity(draft: RuntimeResult) -> tuple[str, int]:
    payload = draft.tool_result or {}
    plan_id = payload.get("plan_id")
    revision = payload.get("revision")
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise ValueError("planning RuntimeResult is missing plan_id.")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("planning RuntimeResult is missing revision.")
    return plan_id, revision


def _merge_plan_steps(
    completed: tuple[PlanStep, ...], current: tuple[PlanStep, ...]
) -> tuple[PlanStep, ...]:
    by_identity = {
        (item.revision, item.step_id): item for item in (*completed, *current)
    }
    return tuple(
        sorted(by_identity.values(), key=lambda item: (item.revision, item.position))
    )


def _plan_invocation(item, plan_id: str) -> PlanExecutorInvocationFacts:
    step = item.plan_step
    if step is None or step.plan_id != plan_id:
        raise ExecutionFeedbackCollectionError(
            "Planning Executor invocation is missing matching PlanStep identity.",
            code="execution_feedback_source_conflict",
        )
    return PlanExecutorInvocationFacts(
        item.executor_invocation_id,
        item.source_span_id,
        step.revision,
        step.step_id,
        item.result,
    )


def _merge_effects(facts: CollectedExecutionFacts) -> tuple[ToolEffectBinding, ...]:
    effects = {}
    for invocation in facts.invocations:
        for binding in invocation.tool_effects:
            previous = effects.get(binding.tool_name)
            if previous is not None and previous is not binding.effect:
                raise ExecutionFeedbackCollectionError(
                    "Tool effect conflicts across Executor invocations.",
                    code="execution_feedback_source_conflict",
                )
            effects[binding.tool_name] = binding.effect
    return tuple(
        ToolEffectBinding(name, effect) for name, effect in sorted(effects.items())
    )


def _step_was_executed(step: PlanStep) -> bool:
    return step.status not in {
        PlanStepStatus.PENDING,
        PlanStepStatus.SUPERSEDED,
        PlanStepStatus.CANCELLED,
    }


def _public_result(draft: RuntimeResult, message: str) -> RuntimeResult:
    return RuntimeResult(
        draft.run_id,
        draft.session_id,
        draft.status,
        message,
        draft.tool_result,
        draft.error_code,
    )


def _feedback_attributes(feedback: ExecutionFeedback) -> dict[str, object]:
    attributes: dict[str, object] = {
        "run_id": feedback.run_id,
        "path": feedback.path.value,
        "status": feedback.overall_status.value,
        "action_count": len(feedback.actions),
        "step_count": len(feedback.plan_steps),
        "evidence_count": sum(len(item.evidence) for item in feedback.actions),
    }
    for name in ("stop_reason", "error_code", "plan_id", "revision", "stop_step_id"):
        value = getattr(feedback, name)
        if value is not None:
            attributes[name] = value
    return attributes


def _record_persistence_projection(
    trace: TraceSink | None,
    feedback: ExecutionFeedback,
    persisted: bool,
) -> None:
    if persisted:
        add_span_event(
            trace,
            "execution.feedback.persisted",
            _feedback_attributes(feedback),
        )
        record_execution_feedback_reference(
            trace,
            safe_reference=f"feedback/{feedback.run_id}",
        )
        return
    add_span_event(
        trace,
        "execution.feedback.failed",
        {
            "run_id": feedback.run_id,
            "path": feedback.path.value,
            "error_code": "execution_feedback_persistence_failed",
        },
    )
