"""Pure construction of safe Direct and Planning ExecutionFeedback."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.common.validation import require_non_empty_string
from app.executor.models import ExecutorResult, ExecutorStatus, ExecutorStopReason
from app.planning.models import PlanRun, PlanRunStatus, PlanStep, PlanStepStatus
from app.recovery.errors import ExecutionFeedbackBuildError
from app.recovery.models import (
    ExecutionActionFeedback,
    ExecutionFeedback,
    ExecutionFeedbackEvidence,
    ExecutionOutcome,
    ExecutionPath,
    ExecutionPlanStepFeedback,
    FeedbackOverallStatus,
    PlanStepOutcome,
    RunGateOutcome,
)
from app.tools.models import ToolCallStatus, ToolEffect


@dataclass(frozen=True)
class ToolEffectBinding:
    tool_name: str
    effect: ToolEffect

    def __post_init__(self) -> None:
        require_non_empty_string(self.tool_name, "tool_name")
        if not isinstance(self.effect, ToolEffect):
            raise ValueError("effect must be a ToolEffect.")


@dataclass(frozen=True)
class DirectExecutionFacts:
    feedback_id: str
    trace_id: str
    run_id: str
    session_id: str
    goal_summary: str
    created_at: str
    result: ExecutorResult | None = None
    executor_invocation_id: str | None = None
    source_span_id: str | None = None
    gate_outcome: RunGateOutcome | None = None
    tool_effects: tuple[ToolEffectBinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in (
            "feedback_id",
            "trace_id",
            "run_id",
            "session_id",
            "goal_summary",
            "created_at",
        ):
            require_non_empty_string(getattr(self, name), name)
        if (self.result is None) == (self.gate_outcome is None):
            raise ValueError("exactly one of result or gate_outcome must be provided.")
        if self.result is not None:
            if not isinstance(self.result, ExecutorResult):
                raise ValueError("result must be ExecutorResult when provided.")
            require_non_empty_string(
                self.executor_invocation_id, "executor_invocation_id"
            )
            require_non_empty_string(self.source_span_id, "source_span_id")
        elif self.executor_invocation_id is not None or self.source_span_id is not None:
            raise ValueError("a zero-execution gate must not contain Executor identity.")
        if self.gate_outcome is not None and not isinstance(
            self.gate_outcome, RunGateOutcome
        ):
            raise ValueError("gate_outcome must be a RunGateOutcome.")
        _effect_bindings(self.tool_effects)


@dataclass(frozen=True)
class PlanExecutorInvocationFacts:
    executor_invocation_id: str
    source_span_id: str
    revision: int
    step_id: str
    result: ExecutorResult

    def __post_init__(self) -> None:
        require_non_empty_string(
            self.executor_invocation_id, "executor_invocation_id"
        )
        require_non_empty_string(self.source_span_id, "source_span_id")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError("revision must be a positive integer.")
        require_non_empty_string(self.step_id, "step_id")
        if not isinstance(self.result, ExecutorResult):
            raise ValueError("result must be an ExecutorResult.")


@dataclass(frozen=True)
class PlanningExecutionFacts:
    feedback_id: str
    trace_id: str
    run_id: str
    session_id: str
    goal_summary: str
    created_at: str
    plan_run: PlanRun
    plan_steps: tuple[PlanStep, ...]
    invocations: tuple[PlanExecutorInvocationFacts, ...]
    tool_effects: tuple[ToolEffectBinding, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in (
            "feedback_id",
            "trace_id",
            "run_id",
            "session_id",
            "goal_summary",
            "created_at",
        ):
            require_non_empty_string(getattr(self, name), name)
        if not isinstance(self.plan_run, PlanRun):
            raise ValueError("plan_run must be a PlanRun.")
        _tuple_of(self.plan_steps, PlanStep, "plan_steps")
        _tuple_of(
            self.invocations, PlanExecutorInvocationFacts, "invocations"
        )
        if not self.plan_steps:
            raise ValueError("plan_steps must not be empty.")
        _effect_bindings(self.tool_effects)


class ExecutionFeedbackBuilder:
    """Build canonical-safe snapshots without storage, telemetry, or providers."""

    def from_direct(self, facts: DirectExecutionFacts) -> ExecutionFeedback:
        if not isinstance(facts, DirectExecutionFacts):
            raise ValueError("facts must be DirectExecutionFacts.")
        if facts.gate_outcome is not None:
            if facts.tool_effects:
                raise _conflict("a zero-execution gate must not contain Tool effects.")
            return ExecutionFeedback(
                feedback_id=facts.feedback_id,
                trace_id=facts.trace_id,
                run_id=facts.run_id,
                session_id=facts.session_id,
                path=ExecutionPath.DIRECT,
                goal_summary=facts.goal_summary,
                overall_status=_status_from_gate(facts.gate_outcome),
                stop_reason=facts.gate_outcome.value,
                error_code=None,
                executor_invocation_ids=(),
                actions=(),
                plan_steps=(),
                created_at=facts.created_at,
            )

        result = facts.result
        if result is None:
            raise _incomplete("Direct ExecutorResult is unavailable.")
        if result.run_id != facts.run_id:
            raise _conflict("ExecutorResult run_id does not match Direct facts.")
        effects = _effect_map(facts.tool_effects)
        actions = _actions_from_result(
            result,
            executor_invocation_id=facts.executor_invocation_id or "",
            source_span_id=facts.source_span_id or "",
            effects=effects,
        )
        return ExecutionFeedback(
            feedback_id=facts.feedback_id,
            trace_id=facts.trace_id,
            run_id=facts.run_id,
            session_id=facts.session_id,
            path=ExecutionPath.DIRECT,
            goal_summary=facts.goal_summary,
            overall_status=_direct_status(result, actions),
            stop_reason=result.stop_reason.value,
            error_code=result.error_code,
            executor_invocation_ids=(facts.executor_invocation_id or "",),
            actions=actions,
            plan_steps=(),
            created_at=facts.created_at,
        )

    def from_plan(self, facts: PlanningExecutionFacts) -> ExecutionFeedback:
        if not isinstance(facts, PlanningExecutionFacts):
            raise ValueError("facts must be PlanningExecutionFacts.")
        run = facts.plan_run
        if run.session_id != facts.session_id:
            raise _conflict("PlanRun session_id does not match Planning facts.")
        if any(item.plan_id != run.plan_id for item in facts.plan_steps):
            raise _conflict("every PlanStep must belong to PlanRun.")
        if len({(item.revision, item.step_id) for item in facts.plan_steps}) != len(
            facts.plan_steps
        ):
            raise _conflict("Planning facts contain duplicate Step identity.")
        step_by_id = {
            (item.revision, item.step_id): item for item in facts.plan_steps
        }
        invocation_by_step: dict[
            tuple[int, str], PlanExecutorInvocationFacts
        ] = {}
        for invocation in facts.invocations:
            key = (invocation.revision, invocation.step_id)
            if key not in step_by_id:
                raise _conflict("Executor invocation references an unknown PlanStep.")
            if key in invocation_by_step:
                raise _conflict("a PlanStep must have at most one Executor invocation.")
            if invocation.result.run_id != facts.run_id:
                raise _conflict("ExecutorResult run_id does not match Planning facts.")
            invocation_by_step[key] = invocation

        ordered_steps = tuple(
            sorted(facts.plan_steps, key=lambda item: (item.revision, item.position))
        )
        effects = _effect_map(facts.tool_effects)
        plan_feedback: list[ExecutionPlanStepFeedback] = []
        actions: list[ExecutionActionFeedback] = []
        executor_ids: list[str] = []
        seen_calls: set[str] = set()
        for step in ordered_steps:
            outcome = _plan_step_outcome(step)
            invocation = invocation_by_step.get((step.revision, step.step_id))
            if outcome is PlanStepOutcome.NOT_RUN and invocation is not None:
                raise _conflict("a not-run PlanStep must not have Executor facts.")
            if outcome is not PlanStepOutcome.NOT_RUN and invocation is None:
                raise _incomplete("an executed PlanStep is missing Executor facts.")
            if invocation is not None:
                _validate_step_invocation(step, outcome, invocation.result)
                executor_ids.append(invocation.executor_invocation_id)
                step_actions = _actions_from_result(
                    invocation.result,
                    executor_invocation_id=invocation.executor_invocation_id,
                    source_span_id=invocation.source_span_id,
                    effects=effects,
                    start_sequence=len(actions) + 1,
                    plan_revision=step.revision,
                    plan_step_id=step.step_id,
                )
                if any(item.call_id in seen_calls for item in step_actions):
                    raise _conflict("Tool call_id must be unique across a Planning run.")
                seen_calls.update(item.call_id for item in step_actions)
                actions.extend(step_actions)
                action_evidence_refs = {
                    ref for item in step_actions for ref in item.evidence_refs
                }
                if not set(step.evidence_refs) <= action_evidence_refs:
                    raise _conflict(
                        "PlanStep evidence_refs must come from its Executor actions."
                    )
            plan_feedback.append(
                ExecutionPlanStepFeedback(
                    revision=step.revision,
                    step_id=step.step_id,
                    position=step.position,
                    objective=step.objective,
                    expected_outcome=step.expected_outcome,
                    original_status=step.status,
                    outcome=outcome,
                    stop_reason=step.stop_reason,
                    error_code=step.error_code,
                    safe_result_summary=step.safe_result_summary,
                    evidence_refs=step.evidence_refs,
                )
            )

        if len(set(executor_ids)) != len(executor_ids):
            raise _conflict("executor_invocation_id must be unique within a run.")
        stop_step = next(
            (
                item
                for item in plan_feedback
                if item.revision == run.current_revision
                and item.outcome is not PlanStepOutcome.COMPLETED
            ),
            None,
        )
        overall = _planning_status(
            tuple(plan_feedback),
            tuple(actions),
            current_revision=run.current_revision,
        )
        if (
            overall is FeedbackOverallStatus.NOT_RUN
            and run.status
            in {
                PlanRunStatus.AWAITING_CONFIRMATION,
                PlanRunStatus.AWAITING_REPLAN_CONFIRMATION,
            }
        ):
            overall = FeedbackOverallStatus.REQUIRES_CONFIRMATION
        if run.status is PlanRunStatus.COMPLETED and any(
            item.revision == run.current_revision
            and item.outcome is not PlanStepOutcome.COMPLETED
            for item in plan_feedback
        ):
            raise _conflict("a completed PlanRun must contain only completed current Steps.")
        return ExecutionFeedback(
            feedback_id=facts.feedback_id,
            trace_id=facts.trace_id,
            run_id=facts.run_id,
            session_id=facts.session_id,
            path=ExecutionPath.PLANNING,
            goal_summary=facts.goal_summary,
            overall_status=overall,
            stop_reason=(stop_step.stop_reason if stop_step is not None else None),
            error_code=run.last_error_code
            or (stop_step.error_code if stop_step is not None else None),
            executor_invocation_ids=tuple(executor_ids),
            actions=tuple(actions),
            plan_steps=tuple(plan_feedback),
            created_at=facts.created_at,
            plan_id=run.plan_id,
            revision=run.current_revision,
            stop_step_id=stop_step.step_id if stop_step is not None else None,
        )


def _actions_from_result(
    result: ExecutorResult,
    *,
    executor_invocation_id: str,
    source_span_id: str,
    effects: dict[str, ToolEffect],
    start_sequence: int = 1,
    plan_revision: int | None = None,
    plan_step_id: str | None = None,
) -> tuple[ExecutionActionFeedback, ...]:
    actions: list[ExecutionActionFeedback] = []
    for offset, observation in enumerate(result.observations):
        effect = effects.get(observation.tool_name)
        if effect is None:
            raise _incomplete(
                f"Tool effect is missing for {observation.tool_name}."
            )
        error = observation.error
        actions.append(
            ExecutionActionFeedback(
                sequence=start_sequence + offset,
                executor_invocation_id=executor_invocation_id,
                source_span_id=source_span_id,
                call_id=observation.call_id,
                tool_name=observation.tool_name,
                tool_effect=effect,
                outcome=_action_outcome(observation.status),
                error_code=error.code if error is not None else None,
                retryable=error.retryable if error is not None else None,
                evidence=tuple(
                    ExecutionFeedbackEvidence(
                        evidence_type=item.evidence_type,
                        summary=item.summary,
                        reference=item.reference,
                        source_call_id=observation.call_id,
                        source_evidence_index=index,
                    )
                    for index, item in enumerate(observation.evidence)
                ),
                plan_revision=plan_revision,
                plan_step_id=plan_step_id,
            )
        )
    return tuple(actions)


def _action_outcome(status: ToolCallStatus) -> ExecutionOutcome:
    return {
        ToolCallStatus.SUCCEEDED: ExecutionOutcome.SUCCEEDED,
        ToolCallStatus.FAILED: ExecutionOutcome.FAILED,
        ToolCallStatus.DENIED: ExecutionOutcome.DENIED,
        ToolCallStatus.REQUIRES_CONFIRMATION: ExecutionOutcome.REQUIRES_CONFIRMATION,
    }[status]


def _plan_step_outcome(step: PlanStep) -> PlanStepOutcome:
    if step.status is PlanStepStatus.COMPLETED:
        return PlanStepOutcome.COMPLETED
    if step.status in {
        PlanStepStatus.PENDING,
        PlanStepStatus.SUPERSEDED,
        PlanStepStatus.CANCELLED,
    }:
        return PlanStepOutcome.NOT_RUN
    if step.status is PlanStepStatus.STOPPED:
        if step.stop_reason == ExecutorStopReason.SAFETY_DENIED.value:
            return PlanStepOutcome.DENIED
        if step.stop_reason == ExecutorStopReason.CONFIRMATION_REQUIRED.value:
            return PlanStepOutcome.REQUIRES_CONFIRMATION
    return PlanStepOutcome.FAILED


def _validate_step_invocation(
    step: PlanStep,
    outcome: PlanStepOutcome,
    result: ExecutorResult,
) -> None:
    if outcome is PlanStepOutcome.COMPLETED and result.status is not ExecutorStatus.COMPLETED:
        raise _conflict("a completed PlanStep requires a completed ExecutorResult.")
    if outcome is PlanStepOutcome.DENIED and result.stop_reason is not ExecutorStopReason.SAFETY_DENIED:
        raise _conflict("a denied PlanStep requires a safety-denied ExecutorResult.")
    if (
        outcome is PlanStepOutcome.REQUIRES_CONFIRMATION
        and result.stop_reason is not ExecutorStopReason.CONFIRMATION_REQUIRED
    ):
        raise _conflict(
            "a confirmation PlanStep requires a confirmation ExecutorResult."
        )


def _direct_status(
    result: ExecutorResult, actions: tuple[ExecutionActionFeedback, ...]
) -> FeedbackOverallStatus:
    outcomes = {item.outcome for item in actions}
    succeeded = ExecutionOutcome.SUCCEEDED in outcomes
    terminal_problem = result.status is not ExecutorStatus.COMPLETED
    if succeeded and (len(outcomes) > 1 or terminal_problem):
        return FeedbackOverallStatus.PARTIAL
    if succeeded:
        return FeedbackOverallStatus.COMPLETED
    if ExecutionOutcome.FAILED in outcomes:
        return FeedbackOverallStatus.FAILED
    if ExecutionOutcome.DENIED in outcomes:
        return FeedbackOverallStatus.DENIED
    if ExecutionOutcome.REQUIRES_CONFIRMATION in outcomes:
        return FeedbackOverallStatus.REQUIRES_CONFIRMATION
    if result.status is ExecutorStatus.COMPLETED:
        return FeedbackOverallStatus.COMPLETED
    if result.stop_reason is ExecutorStopReason.SAFETY_DENIED:
        return FeedbackOverallStatus.DENIED
    if result.stop_reason is ExecutorStopReason.CONFIRMATION_REQUIRED:
        return FeedbackOverallStatus.REQUIRES_CONFIRMATION
    return FeedbackOverallStatus.FAILED


def _planning_status(
    steps: tuple[ExecutionPlanStepFeedback, ...],
    actions: tuple[ExecutionActionFeedback, ...],
    *,
    current_revision: int,
) -> FeedbackOverallStatus:
    relevant = tuple(
        item
        for item in steps
        if item.revision == current_revision
        or item.outcome is not PlanStepOutcome.NOT_RUN
    )
    outcomes = {item.outcome for item in relevant}
    action_outcomes = {item.outcome for item in actions}
    verified_success = (
        PlanStepOutcome.COMPLETED in outcomes
        or ExecutionOutcome.SUCCEEDED in action_outcomes
    )
    has_problem = (
        any(item is not PlanStepOutcome.COMPLETED for item in outcomes)
        or any(item is not ExecutionOutcome.SUCCEEDED for item in action_outcomes)
    )
    if verified_success and has_problem:
        return FeedbackOverallStatus.PARTIAL
    if outcomes == {PlanStepOutcome.COMPLETED}:
        return FeedbackOverallStatus.COMPLETED
    if PlanStepOutcome.FAILED in outcomes:
        return FeedbackOverallStatus.FAILED
    if PlanStepOutcome.DENIED in outcomes:
        return FeedbackOverallStatus.DENIED
    if PlanStepOutcome.REQUIRES_CONFIRMATION in outcomes:
        return FeedbackOverallStatus.REQUIRES_CONFIRMATION
    return FeedbackOverallStatus.NOT_RUN


def _status_from_gate(outcome: RunGateOutcome) -> FeedbackOverallStatus:
    return FeedbackOverallStatus(outcome.value)


def _effect_bindings(bindings: tuple[ToolEffectBinding, ...]) -> None:
    _tuple_of(bindings, ToolEffectBinding, "tool_effects")
    if len({item.tool_name for item in bindings}) != len(bindings):
        raise ValueError("tool_effects must not contain duplicate tool names.")


def _effect_map(bindings: tuple[ToolEffectBinding, ...]) -> dict[str, ToolEffect]:
    return {item.tool_name: item.effect for item in bindings}


def _tuple_of(values: object, item_type: type, field_name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, item_type) for item in values
    ):
        raise ValueError(f"{field_name} must contain {item_type.__name__} values.")


def _conflict(message: str) -> ExecutionFeedbackBuildError:
    return ExecutionFeedbackBuildError(
        message, code="execution_feedback_source_conflict"
    )


def _incomplete(message: str) -> ExecutionFeedbackBuildError:
    return ExecutionFeedbackBuildError(
        message, code="execution_feedback_source_incomplete"
    )
