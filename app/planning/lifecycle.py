"""Pure lifecycle, dependency scheduling, and budget rules for plans."""

from __future__ import annotations

from dataclasses import replace

from app.planning.errors import PlanContractError, PlanLifecycleError
from app.planning.models import (
    PlanDraft,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepStatus,
    PlanningLimits,
)


_RUN_TRANSITIONS = {
    PlanRunStatus.AWAITING_CONFIRMATION: {
        PlanRunStatus.RUNNING,
        PlanRunStatus.CANCELLED,
    },
    PlanRunStatus.RUNNING: {
        PlanRunStatus.AWAITING_REPLAN_CONFIRMATION,
        PlanRunStatus.COMPLETED,
        PlanRunStatus.STOPPED,
        PlanRunStatus.FAILED,
    },
    PlanRunStatus.AWAITING_REPLAN_CONFIRMATION: {
        PlanRunStatus.RUNNING,
        PlanRunStatus.CANCELLED,
    },
}

_STEP_TRANSITIONS = {
    PlanStepStatus.PENDING: {
        PlanStepStatus.RUNNING,
        PlanStepStatus.SUPERSEDED,
        PlanStepStatus.CANCELLED,
    },
    PlanStepStatus.RUNNING: {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.GOAL_NOT_ACHIEVED,
        PlanStepStatus.STOPPED,
        PlanStepStatus.FAILED,
    },
}


def validate_plan_draft(draft: PlanDraft, limits: PlanningLimits) -> None:
    """Validate bounded positions and acyclic dependencies."""
    if not isinstance(draft, PlanDraft) or not isinstance(limits, PlanningLimits):
        raise PlanContractError("Plan validation input is invalid.", code="plan_contract_invalid")
    if len(draft.steps) > limits.max_plan_steps:
        raise PlanContractError("Plan has too many steps.", code="plan_contract_invalid")
    positions = sorted(item.position for item in draft.steps)
    if positions != list(range(1, len(draft.steps) + 1)):
        raise PlanContractError(
            "Plan positions must be contiguous and start at one.",
            code="plan_dependency_invalid",
        )
    dependencies = {item.step_id: item.dependency_step_ids for item in draft.steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise PlanContractError(
                "Plan dependencies contain a cycle.",
                code="plan_dependency_invalid",
            )
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in dependencies:
        visit(step_id)


def validate_step_set(steps: tuple[PlanStep, ...]) -> None:
    """Validate persisted steps belong to one plan revision and match a valid draft."""
    if not isinstance(steps, tuple) or not steps:
        raise PlanContractError("Plan steps must not be empty.", code="plan_contract_invalid")
    if any(not isinstance(item, PlanStep) for item in steps):
        raise PlanContractError("Plan steps are invalid.", code="plan_contract_invalid")
    identities = {(item.plan_id, item.revision) for item in steps}
    if len(identities) != 1:
        raise PlanContractError(
            "Plan steps must belong to one revision.", code="plan_dependency_invalid"
        )
    draft = PlanDraft(tuple(_to_draft(item) for item in steps))
    validate_plan_draft(draft, PlanningLimits(max_plan_steps=max(6, len(steps))))
    if sum(item.status == PlanStepStatus.RUNNING for item in steps) > 1:
        raise PlanContractError(
            "Only one plan step may be running.", code="plan_dependency_invalid"
        )


def ready_steps(steps: tuple[PlanStep, ...]) -> tuple[PlanStep, ...]:
    """Return dependency-ready pending steps in stable position order."""
    validate_step_set(steps)
    if any(item.status == PlanStepStatus.RUNNING for item in steps):
        return ()
    completed = {item.step_id for item in steps if item.status == PlanStepStatus.COMPLETED}
    return tuple(
        sorted(
            (
                item
                for item in steps
                if item.status == PlanStepStatus.PENDING
                and set(item.dependency_step_ids).issubset(completed)
            ),
            key=lambda item: item.position,
        )
    )


def transition_plan_run(run: PlanRun, target: PlanRunStatus, *, at: str | None = None) -> PlanRun:
    if target not in _RUN_TRANSITIONS.get(run.status, set()):
        raise PlanLifecycleError(
            "Plan run transition is not allowed.", code="plan_command_not_allowed"
        )
    values: dict[str, object] = {"status": target, "updated_at": at or run.updated_at}
    if target == PlanRunStatus.RUNNING and run.confirmed_at is None:
        values["confirmed_at"] = at
    if target in {
        PlanRunStatus.COMPLETED,
        PlanRunStatus.STOPPED,
        PlanRunStatus.FAILED,
        PlanRunStatus.CANCELLED,
    }:
        values["completed_at"] = at
    return replace(run, **values)


def transition_plan_step(
    step: PlanStep,
    target: PlanStepStatus,
    *,
    at: str | None = None,
    safe_result_summary: str | None = None,
    stop_reason: str | None = None,
    error_code: str | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> PlanStep:
    if target not in _STEP_TRANSITIONS.get(step.status, set()):
        raise PlanLifecycleError(
            "Plan step transition is not allowed.", code="plan_command_not_allowed"
        )
    if target == PlanStepStatus.COMPLETED and not safe_result_summary:
        raise PlanLifecycleError(
            "Completed step requires a safe result summary.", code="plan_contract_invalid"
        )
    values: dict[str, object] = {"status": target}
    if target == PlanStepStatus.RUNNING:
        values["started_at"] = at
    else:
        values.update(
            completed_at=at,
            safe_result_summary=safe_result_summary,
            stop_reason=stop_reason,
            error_code=error_code,
            evidence_refs=evidence_refs,
        )
    return replace(step, **values)


def record_executor_usage(
    run: PlanRun,
    step: PlanStep,
    used_steps: int,
    limits: PlanningLimits,
) -> tuple[PlanRun, PlanStep]:
    if not isinstance(used_steps, int) or isinstance(used_steps, bool) or used_steps < 0:
        raise PlanLifecycleError("Executor usage is invalid.", code="plan_contract_invalid")
    if step.plan_id != run.plan_id or step.revision != run.current_revision:
        raise PlanLifecycleError("Plan revision is stale.", code="plan_revision_stale")
    if used_steps > limits.max_executor_steps_per_plan_step:
        raise PlanLifecycleError("Plan step budget is exhausted.", code="plan_budget_exhausted")
    if run.executor_steps_used + used_steps > limits.max_total_executor_steps:
        raise PlanLifecycleError("Plan run budget is exhausted.", code="plan_budget_exhausted")
    return (
        replace(run, executor_steps_used=run.executor_steps_used + used_steps),
        replace(step, executor_steps_used=step.executor_steps_used + used_steps),
    )


def remaining_step_limit(run: PlanRun, limits: PlanningLimits) -> int:
    remaining = max(0, limits.max_total_executor_steps - run.executor_steps_used)
    return min(limits.max_executor_steps_per_plan_step, remaining)


def is_replan_eligible(run: PlanRun, failed_step: PlanStep, limits: PlanningLimits) -> bool:
    return (
        run.status == PlanRunStatus.RUNNING
        and failed_step.plan_id == run.plan_id
        and failed_step.revision == run.current_revision
        and (
            failed_step.status == PlanStepStatus.GOAL_NOT_ACHIEVED
            or (
                failed_step.status == PlanStepStatus.STOPPED
                and failed_step.stop_reason == "limit_reached"
            )
        )
        and run.replan_count < limits.max_replans
        and remaining_step_limit(run, limits) > 0
    )


def _to_draft(step: PlanStep):
    from app.planning.models import PlanStepDraft

    return PlanStepDraft(
        step.step_id,
        step.position,
        step.objective,
        step.expected_outcome,
        step.dependency_step_ids,
    )
