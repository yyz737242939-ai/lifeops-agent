"""Pure public models for Plan-and-Execute planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.common.validation import (
    require_non_empty_string,
    require_unique_non_empty_strings,
)
from app.skills.models import PromptContribution


@dataclass(frozen=True)
class PlanningLimits:
    max_plan_steps: int = 6
    max_replans: int = 1
    max_executor_steps_per_plan_step: int = 6
    max_total_executor_steps: int = 24

    def __post_init__(self) -> None:
        for name, value in (
            ("max_plan_steps", self.max_plan_steps),
            ("max_replans", self.max_replans),
            ("max_executor_steps_per_plan_step", self.max_executor_steps_per_plan_step),
            ("max_total_executor_steps", self.max_total_executor_steps),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        if self.max_plan_steps < 1:
            raise ValueError("max_plan_steps must be positive.")
        if self.max_executor_steps_per_plan_step < 1:
            raise ValueError("max_executor_steps_per_plan_step must be positive.")
        if self.max_total_executor_steps < 1:
            raise ValueError("max_total_executor_steps must be positive.")


@dataclass(frozen=True)
class DirectRoute:
    reason_code: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.reason_code, "reason_code")


@dataclass(frozen=True)
class PlanRoute:
    reason_code: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.reason_code, "reason_code")


@dataclass(frozen=True)
class NeedUserRoute:
    question: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.question, "question")


PlanningRouteDecision = DirectRoute | PlanRoute | NeedUserRoute


@dataclass(frozen=True)
class PlanningScopeRef:
    domain: str
    scope_id: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.domain, "domain")
        require_non_empty_string(self.scope_id, "scope_id")


@dataclass(frozen=True)
class PlanningSnapshotEnvelope:
    domain: str
    scope_id: str
    snapshot: dict[str, Any]

    def __post_init__(self) -> None:
        require_non_empty_string(self.domain, "domain")
        require_non_empty_string(self.scope_id, "scope_id")
        if not isinstance(self.snapshot, dict):
            raise ValueError("snapshot must be a dict.")


@dataclass(frozen=True)
class PlanningRouteInput:
    goal: str
    intent_summary: str
    prompt_contributions: tuple[PromptContribution, ...] = field(default_factory=tuple)
    tool_catalog: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    limits: PlanningLimits = field(default_factory=PlanningLimits)

    def __post_init__(self) -> None:
        require_non_empty_string(self.goal, "goal")
        require_non_empty_string(self.intent_summary, "intent_summary")
        _require_tuple_of(self.prompt_contributions, PromptContribution, "prompt_contributions")
        if not isinstance(self.tool_catalog, tuple) or any(
            not isinstance(item, dict) for item in self.tool_catalog
        ):
            raise ValueError("tool_catalog must contain dict values.")
        if not isinstance(self.limits, PlanningLimits):
            raise ValueError("limits must be PlanningLimits.")


class PlanRunStatus(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    AWAITING_REPLAN_CONFIRMATION = "awaiting_replan_confirmation"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    GOAL_NOT_ACHIEVED = "goal_not_achieved"
    STOPPED = "stopped"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PlanStepDraft:
    step_id: str
    position: int
    objective: str
    expected_outcome: str
    dependency_step_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.step_id, "step_id")
        if not isinstance(self.position, int) or isinstance(self.position, bool) or self.position < 1:
            raise ValueError("position must be a positive integer.")
        require_non_empty_string(self.objective, "objective")
        require_non_empty_string(self.expected_outcome, "expected_outcome")
        require_unique_non_empty_strings(self.dependency_step_ids, "dependency_step_ids")
        if self.step_id in self.dependency_step_ids:
            raise ValueError("a plan step cannot depend on itself.")


@dataclass(frozen=True)
class PlanDraft:
    steps: tuple[PlanStepDraft, ...]

    def __post_init__(self) -> None:
        _require_tuple_of(self.steps, PlanStepDraft, "steps")
        if not self.steps:
            raise ValueError("steps must not be empty.")
        step_ids = tuple(item.step_id for item in self.steps)
        positions = tuple(item.position for item in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("step_id must be unique within a plan draft.")
        if len(set(positions)) != len(positions):
            raise ValueError("position must be unique within a plan draft.")
        known = set(step_ids)
        if any(dependency not in known for item in self.steps for dependency in item.dependency_step_ids):
            raise ValueError("every dependency must reference a step in the same draft.")


@dataclass(frozen=True)
class PlannerNeedUser:
    question: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.question, "question")


PlanDraftResult = PlanDraft | PlannerNeedUser


@dataclass(frozen=True)
class PlanRun:
    plan_id: str
    session_id: str
    goal: str
    status: PlanRunStatus
    current_revision: int = 1
    replan_count: int = 0
    executor_steps_used: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    confirmed_at: str | None = None
    completed_at: str | None = None
    last_error_code: str | None = None
    confirmed_constraints: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.plan_id, "plan_id")
        require_non_empty_string(self.session_id, "session_id")
        require_non_empty_string(self.goal, "goal")
        if not isinstance(self.status, PlanRunStatus):
            raise ValueError("status must be PlanRunStatus.")
        _require_positive_int(self.current_revision, "current_revision")
        _require_non_negative_int(self.replan_count, "replan_count")
        _require_non_negative_int(self.executor_steps_used, "executor_steps_used")
        require_unique_non_empty_strings(
            self.confirmed_constraints, "confirmed_constraints"
        )
        _validate_optional_strings(self)


@dataclass(frozen=True)
class PlanStep:
    plan_id: str
    revision: int
    step_id: str
    position: int
    objective: str
    expected_outcome: str
    dependency_step_ids: tuple[str, ...]
    status: PlanStepStatus
    stop_reason: str | None = None
    safe_result_summary: str | None = None
    error_code: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    executor_steps_used: int = 0
    started_at: str | None = None
    completed_at: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_string(self.plan_id, "plan_id")
        _require_positive_int(self.revision, "revision")
        PlanStepDraft(
            step_id=self.step_id,
            position=self.position,
            objective=self.objective,
            expected_outcome=self.expected_outcome,
            dependency_step_ids=self.dependency_step_ids,
        )
        if not isinstance(self.status, PlanStepStatus):
            raise ValueError("status must be PlanStepStatus.")
        if self.status == PlanStepStatus.COMPLETED and self.safe_result_summary is None:
            raise ValueError("completed plan step must contain safe_result_summary.")
        require_unique_non_empty_strings(self.evidence_refs, "evidence_refs")
        _require_non_negative_int(self.executor_steps_used, "executor_steps_used")
        _validate_optional_strings(self)


class PlanCommandAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    MODIFY = "modify"


@dataclass(frozen=True)
class PlanCommand:
    command_id: str
    plan_id: str
    session_id: str
    revision: int
    action: PlanCommandAction
    feedback: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_string(self.command_id, "command_id")
        require_non_empty_string(self.plan_id, "plan_id")
        require_non_empty_string(self.session_id, "session_id")
        _require_positive_int(self.revision, "revision")
        if not isinstance(self.action, PlanCommandAction):
            raise ValueError("action must be PlanCommandAction.")
        if self.action == PlanCommandAction.MODIFY:
            require_non_empty_string(self.feedback, "feedback")
        elif self.feedback is not None:
            raise ValueError("feedback is only allowed for modify commands.")


@dataclass(frozen=True)
class PlannerInput:
    goal: str
    prompt_contributions: tuple[PromptContribution, ...]
    tool_catalog: tuple[dict[str, Any], ...]
    limits: PlanningLimits
    snapshots: tuple[PlanningSnapshotEnvelope, ...] = field(default_factory=tuple)
    confirmed_constraints: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.goal, "goal")
        _require_tuple_of(self.prompt_contributions, PromptContribution, "prompt_contributions")
        if not isinstance(self.tool_catalog, tuple) or any(not isinstance(item, dict) for item in self.tool_catalog):
            raise ValueError("tool_catalog must contain dict values.")
        if not isinstance(self.limits, PlanningLimits):
            raise ValueError("limits must be PlanningLimits.")
        _require_tuple_of(self.snapshots, PlanningSnapshotEnvelope, "snapshots")
        if len({(item.domain, item.scope_id) for item in self.snapshots}) != len(self.snapshots):
            raise ValueError("snapshots must not contain duplicate scope envelopes.")
        require_unique_non_empty_strings(self.confirmed_constraints, "confirmed_constraints")


@dataclass(frozen=True)
class ReplanInput:
    planner_input: PlannerInput
    completed_steps: tuple[PlanStep, ...]
    failed_step: PlanStep
    confirmed_constraints: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.planner_input, PlannerInput):
            raise ValueError("planner_input must be PlannerInput.")
        _require_tuple_of(self.completed_steps, PlanStep, "completed_steps")
        if not isinstance(self.failed_step, PlanStep):
            raise ValueError("failed_step must be PlanStep.")
        require_unique_non_empty_strings(self.confirmed_constraints, "confirmed_constraints")


@dataclass(frozen=True)
class PlanPreview:
    run: PlanRun
    steps: tuple[PlanStep, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run, PlanRun):
            raise ValueError("run must be PlanRun.")
        _require_tuple_of(self.steps, PlanStep, "steps")
        if not self.steps:
            raise ValueError("steps must not be empty.")
        if any(
            item.plan_id != self.run.plan_id
            or item.revision != self.run.current_revision
            for item in self.steps
        ):
            raise ValueError("preview steps must belong to the current plan revision.")


@dataclass(frozen=True)
class PlanFinalizerStepResult:
    step_id: str
    position: int
    status: PlanStepStatus
    safe_result_summary: str | None = None
    stop_reason: str | None = None
    error_code: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.step_id, "step_id")
        _require_positive_int(self.position, "position")
        if not isinstance(self.status, PlanStepStatus):
            raise ValueError("status must be PlanStepStatus.")
        if self.status == PlanStepStatus.COMPLETED:
            require_non_empty_string(self.safe_result_summary, "safe_result_summary")
        require_unique_non_empty_strings(self.evidence_refs, "evidence_refs")
        _validate_optional_strings(self)


@dataclass(frozen=True)
class PlanFinalizerInput:
    goal: str
    revision: int
    step_results: tuple[PlanFinalizerStepResult, ...]

    def __post_init__(self) -> None:
        require_non_empty_string(self.goal, "goal")
        _require_positive_int(self.revision, "revision")
        _require_tuple_of(self.step_results, PlanFinalizerStepResult, "step_results")
        if not self.step_results:
            raise ValueError("step_results must not be empty.")
        if len({item.step_id for item in self.step_results}) != len(self.step_results):
            raise ValueError("step_results must have unique step IDs.")
        if tuple(item.position for item in self.step_results) != tuple(
            range(1, len(self.step_results) + 1)
        ):
            raise ValueError("step_results must be in contiguous position order.")


@dataclass(frozen=True)
class PlanFinalizerOutput:
    message: str
    claims_write_success: bool = False
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.message, "message")
        if not isinstance(self.claims_write_success, bool):
            raise ValueError("claims_write_success must be bool.")
        require_unique_non_empty_strings(self.evidence_refs, "evidence_refs")


def _require_tuple_of(values: object, item_type: type, field_name: str) -> None:
    if not isinstance(values, tuple) or any(not isinstance(item, item_type) for item in values):
        raise ValueError(f"{field_name} must contain {item_type.__name__} values.")


def _require_positive_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


def _require_non_negative_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")


def _validate_optional_strings(value: object) -> None:
    for field_name, field_value in vars(value).items():
        if (field_name.endswith("_at") or field_name in {"stop_reason", "safe_result_summary", "error_code", "last_error_code"}) and field_value is not None:
            require_non_empty_string(field_value, field_name)
