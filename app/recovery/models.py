"""Framework-independent models for Execution Feedback and Recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.common.validation import (
    require_non_empty_string,
    require_unique_non_empty_strings,
)
from app.planning.models import PlanStepStatus
from app.tools.models import ToolEffect


class ExecutionPath(StrEnum):
    DIRECT = "direct"
    PLANNING = "planning"


class ExecutionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class FeedbackOverallStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    DENIED = "denied"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    NOT_RUN = "not_run"


class PlanStepOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    NOT_RUN = "not_run"


class RunGateOutcome(StrEnum):
    DENIED = "denied"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    NOT_RUN = "not_run"


class ExecutionClaimKind(StrEnum):
    ACTION_SUCCESS = "action_success"
    PLAN_STEP_SUCCESS = "plan_step_success"


class ClaimStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class AnswerOutputMode(StrEnum):
    MODEL = "model"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class RecoveryOutputMode(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL = "model"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


@dataclass(frozen=True)
class ExecutionFeedbackEvidence:
    evidence_type: str
    summary: str
    reference: str | None
    source_call_id: str
    source_evidence_index: int

    def __post_init__(self) -> None:
        require_non_empty_string(self.evidence_type, "evidence_type")
        require_non_empty_string(self.summary, "summary")
        _optional_text(self.reference, "reference")
        require_non_empty_string(self.source_call_id, "source_call_id")
        if (
            not isinstance(self.source_evidence_index, int)
            or isinstance(self.source_evidence_index, bool)
            or self.source_evidence_index < 0
        ):
            raise ValueError("source_evidence_index must be a non-negative integer.")


@dataclass(frozen=True)
class ExecutionActionFeedback:
    sequence: int
    executor_invocation_id: str
    source_span_id: str
    call_id: str
    tool_name: str
    tool_effect: ToolEffect
    outcome: ExecutionOutcome
    error_code: str | None = None
    retryable: bool | None = None
    evidence: tuple[ExecutionFeedbackEvidence, ...] = field(default_factory=tuple)
    plan_revision: int | None = None
    plan_step_id: str | None = None

    def __post_init__(self) -> None:
        _positive_int(self.sequence, "sequence")
        for name in (
            "executor_invocation_id",
            "source_span_id",
            "call_id",
            "tool_name",
        ):
            require_non_empty_string(getattr(self, name), name)
        if not isinstance(self.tool_effect, ToolEffect):
            raise ValueError("tool_effect must be a ToolEffect.")
        if not isinstance(self.outcome, ExecutionOutcome):
            raise ValueError("outcome must be an ExecutionOutcome.")
        _optional_text(self.error_code, "error_code")
        if self.retryable is not None and not isinstance(self.retryable, bool):
            raise ValueError("retryable must be bool when provided.")
        _tuple_of(self.evidence, ExecutionFeedbackEvidence, "evidence")
        if any(item.source_call_id != self.call_id for item in self.evidence):
            raise ValueError("evidence must belong to the action call_id.")
        if len({item.source_evidence_index for item in self.evidence}) != len(
            self.evidence
        ):
            raise ValueError("evidence indexes must be unique within an action.")
        if self.outcome is ExecutionOutcome.SUCCEEDED and self.error_code is not None:
            raise ValueError("a succeeded action must not contain error_code.")
        if (self.plan_revision is None) != (self.plan_step_id is None):
            raise ValueError("plan_revision and plan_step_id must be provided together.")
        if self.plan_revision is not None:
            _positive_int(self.plan_revision, "plan_revision")
            require_non_empty_string(self.plan_step_id, "plan_step_id")

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(item.reference for item in self.evidence if item.reference is not None)


@dataclass(frozen=True)
class ExecutionPlanStepFeedback:
    revision: int
    step_id: str
    position: int
    objective: str
    expected_outcome: str
    original_status: PlanStepStatus
    outcome: PlanStepOutcome
    stop_reason: str | None = None
    error_code: str | None = None
    safe_result_summary: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _positive_int(self.revision, "revision")
        require_non_empty_string(self.step_id, "step_id")
        _positive_int(self.position, "position")
        require_non_empty_string(self.objective, "objective")
        require_non_empty_string(self.expected_outcome, "expected_outcome")
        if not isinstance(self.original_status, PlanStepStatus):
            raise ValueError("original_status must be a PlanStepStatus.")
        if not isinstance(self.outcome, PlanStepOutcome):
            raise ValueError("outcome must be a PlanStepOutcome.")
        for name in ("stop_reason", "error_code", "safe_result_summary"):
            _optional_text(getattr(self, name), name)
        require_unique_non_empty_strings(self.evidence_refs, "evidence_refs")
        if self.outcome is PlanStepOutcome.COMPLETED and self.safe_result_summary is None:
            raise ValueError("a completed step must contain safe_result_summary.")


@dataclass(frozen=True)
class FinalAnswerValidation:
    claim_status: ClaimStatus
    output_mode: AnswerOutputMode
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    accepted_claim_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.claim_status, ClaimStatus):
            raise ValueError("claim_status must be a ClaimStatus.")
        if not isinstance(self.output_mode, AnswerOutputMode):
            raise ValueError("output_mode must be an AnswerOutputMode.")
        require_unique_non_empty_strings(self.reason_codes, "reason_codes")
        require_unique_non_empty_strings(
            self.accepted_claim_ids, "accepted_claim_ids"
        )
        expected_mode = (
            AnswerOutputMode.MODEL
            if self.claim_status is ClaimStatus.VALID
            else AnswerOutputMode.DETERMINISTIC_FALLBACK
        )
        if self.output_mode is not expected_mode:
            raise ValueError("output_mode must match claim_status.")
        if self.claim_status is ClaimStatus.VALID and self.reason_codes:
            raise ValueError("valid claims must not contain reason_codes.")
        if self.claim_status is ClaimStatus.INVALID and not self.reason_codes:
            raise ValueError("invalid claims must contain reason_codes.")


@dataclass(frozen=True)
class ExecutionFeedback:
    feedback_id: str
    trace_id: str
    run_id: str
    session_id: str
    path: ExecutionPath
    goal_summary: str
    overall_status: FeedbackOverallStatus
    stop_reason: str | None
    error_code: str | None
    executor_invocation_ids: tuple[str, ...]
    actions: tuple[ExecutionActionFeedback, ...]
    plan_steps: tuple[ExecutionPlanStepFeedback, ...]
    created_at: str
    plan_id: str | None = None
    revision: int | None = None
    stop_step_id: str | None = None
    validation: FinalAnswerValidation | None = None

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
        if not isinstance(self.path, ExecutionPath):
            raise ValueError("path must be an ExecutionPath.")
        if not isinstance(self.overall_status, FeedbackOverallStatus):
            raise ValueError("overall_status must be a FeedbackOverallStatus.")
        _optional_text(self.stop_reason, "stop_reason")
        _optional_text(self.error_code, "error_code")
        require_unique_non_empty_strings(
            self.executor_invocation_ids, "executor_invocation_ids"
        )
        _tuple_of(self.actions, ExecutionActionFeedback, "actions")
        _tuple_of(self.plan_steps, ExecutionPlanStepFeedback, "plan_steps")
        if tuple(item.sequence for item in self.actions) != tuple(
            range(1, len(self.actions) + 1)
        ):
            raise ValueError("actions must use contiguous sequence order.")
        if len({item.call_id for item in self.actions}) != len(self.actions):
            raise ValueError("actions must not contain duplicate call_id values.")
        if any(
            item.executor_invocation_id not in self.executor_invocation_ids
            for item in self.actions
        ):
            raise ValueError("every action must reference a known executor invocation.")
        if self.path is ExecutionPath.DIRECT:
            if any(
                value is not None
                for value in (self.plan_id, self.revision, self.stop_step_id)
            ) or self.plan_steps:
                raise ValueError("direct feedback must not contain planning identity.")
        else:
            require_non_empty_string(self.plan_id, "plan_id")
            _positive_int(self.revision, "revision")
            _optional_text(self.stop_step_id, "stop_step_id")
            if not self.plan_steps:
                raise ValueError("planning feedback must contain plan_steps.")
        if self.validation is not None and not isinstance(
            self.validation, FinalAnswerValidation
        ):
            raise ValueError("validation must be FinalAnswerValidation when provided.")


@dataclass(frozen=True)
class ExecutionClaim:
    claim_id: str
    kind: ExecutionClaimKind
    source_run_id: str
    session_id: str
    call_id: str | None = None
    plan_id: str | None = None
    plan_revision: int | None = None
    plan_step_id: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.claim_id, "claim_id")
        if not isinstance(self.kind, ExecutionClaimKind):
            raise ValueError("kind must be an ExecutionClaimKind.")
        require_non_empty_string(self.source_run_id, "source_run_id")
        require_non_empty_string(self.session_id, "session_id")
        require_unique_non_empty_strings(self.evidence_refs, "evidence_refs")
        for name in ("call_id", "plan_id", "plan_step_id"):
            _optional_text(getattr(self, name), name)
        if self.plan_revision is not None:
            _positive_int(self.plan_revision, "plan_revision")
        if self.kind is ExecutionClaimKind.ACTION_SUCCESS:
            require_non_empty_string(self.call_id, "call_id")
            if self.plan_step_id is not None and (
                self.plan_id is None or self.plan_revision is None
            ):
                raise ValueError("planning action claims require full plan identity.")
        else:
            if self.call_id is not None:
                raise ValueError("plan step claims must not contain call_id.")
            require_non_empty_string(self.plan_id, "plan_id")
            _positive_int(self.plan_revision, "plan_revision")
            require_non_empty_string(self.plan_step_id, "plan_step_id")


@dataclass(frozen=True)
class FinalAnswerDraft:
    message: str
    execution_claims: tuple[ExecutionClaim, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.message, "message")
        _tuple_of(self.execution_claims, ExecutionClaim, "execution_claims")
        if len({item.claim_id for item in self.execution_claims}) != len(
            self.execution_claims
        ):
            raise ValueError("execution_claims must have unique claim_id values.")


@dataclass(frozen=True)
class ValidatedFinalAnswer:
    message: str
    validation: FinalAnswerValidation

    def __post_init__(self) -> None:
        require_non_empty_string(self.message, "message")
        if not isinstance(self.validation, FinalAnswerValidation):
            raise ValueError("validation must be FinalAnswerValidation.")


@dataclass(frozen=True)
class RecoveryStopPoint:
    overall_status: FeedbackOverallStatus
    stop_reason: str | None = None
    error_code: str | None = None
    call_id: str | None = None
    plan_step_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.overall_status, FeedbackOverallStatus):
            raise ValueError("overall_status must be a FeedbackOverallStatus.")
        for name in ("stop_reason", "error_code", "call_id", "plan_step_id"):
            _optional_text(getattr(self, name), name)


@dataclass(frozen=True)
class RecoveryContext:
    source_trace_id: str
    source_run_id: str
    session_id: str
    goal_summary: str
    path: ExecutionPath
    stop_point: RecoveryStopPoint
    succeeded_actions: tuple[ExecutionActionFeedback, ...]
    failed_actions: tuple[ExecutionActionFeedback, ...]
    completed_steps: tuple[ExecutionPlanStepFeedback, ...]
    failed_steps: tuple[ExecutionPlanStepFeedback, ...]
    not_run_steps: tuple[ExecutionPlanStepFeedback, ...]
    durable_evidence: tuple[ExecutionFeedbackEvidence, ...]
    safe_next_steps: tuple[str, ...]
    generated_at: str

    def __post_init__(self) -> None:
        for name in (
            "source_trace_id",
            "source_run_id",
            "session_id",
            "goal_summary",
            "generated_at",
        ):
            require_non_empty_string(getattr(self, name), name)
        if not isinstance(self.path, ExecutionPath):
            raise ValueError("path must be an ExecutionPath.")
        if not isinstance(self.stop_point, RecoveryStopPoint):
            raise ValueError("stop_point must be a RecoveryStopPoint.")
        _tuple_of(self.succeeded_actions, ExecutionActionFeedback, "succeeded_actions")
        _tuple_of(self.failed_actions, ExecutionActionFeedback, "failed_actions")
        _tuple_of(self.completed_steps, ExecutionPlanStepFeedback, "completed_steps")
        _tuple_of(self.failed_steps, ExecutionPlanStepFeedback, "failed_steps")
        _tuple_of(self.not_run_steps, ExecutionPlanStepFeedback, "not_run_steps")
        _tuple_of(self.durable_evidence, ExecutionFeedbackEvidence, "durable_evidence")
        require_unique_non_empty_strings(self.safe_next_steps, "safe_next_steps")


@dataclass(frozen=True)
class RecoveryResult:
    context: RecoveryContext
    explanation: str
    output_mode: RecoveryOutputMode
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.context, RecoveryContext):
            raise ValueError("context must be a RecoveryContext.")
        require_non_empty_string(self.explanation, "explanation")
        if not isinstance(self.output_mode, RecoveryOutputMode):
            raise ValueError("output_mode must be a RecoveryOutputMode.")
        _optional_text(self.error_code, "error_code")


def _positive_int(value: int | None, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


def _optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        require_non_empty_string(value, field_name)


def _tuple_of(values: object, item_type: type, field_name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, item_type) for item in values
    ):
        raise ValueError(f"{field_name} must contain {item_type.__name__} values.")
