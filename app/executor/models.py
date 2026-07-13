"""Framework-independent models for bounded Executor decisions and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.common.validation import require_non_empty_string
from app.runtime.models import RuntimeRequest
from app.skills.models import PromptContribution
from app.tools.models import (
    ExecutionEvidence,
    ToolCall,
    ToolCallStatus,
    ToolError,
    ToolResult,
)


class ExecutorStatus(StrEnum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class ExecutorStopReason(StrEnum):
    FINAL_ANSWER = "final_answer"
    CONFIRMATION_REQUIRED = "confirmation_required"
    LIMIT_REACHED = "limit_reached"
    SAFETY_DENIED = "safety_denied"
    MODEL_FAILED = "model_failed"
    INVALID_MODEL_ACTION = "invalid_model_action"
    INPUT_PROVIDER_FAILED = "input_provider_failed"
    EXECUTOR_INTERNAL_FAILED = "executor_internal_failed"


@dataclass(frozen=True)
class ExecutionLimits:
    """Composition-owned bounds for one Executor invocation."""

    max_steps: int = 8

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_steps, int)
            or isinstance(self.max_steps, bool)
            or not 1 <= self.max_steps <= 16
        ):
            raise ValueError("max_steps must be an integer from 1 through 16.")


@dataclass(frozen=True)
class ToolActionDecision:
    """A model decision requesting exactly one ToolCall."""

    call: ToolCall

    def __post_init__(self) -> None:
        if not isinstance(self.call, ToolCall):
            raise ValueError("call must be a ToolCall.")


@dataclass(frozen=True)
class FinalAnswerDecision:
    """A model decision returning a non-empty user-facing answer."""

    message: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.message, "message")


ExecutorDecision = ToolActionDecision | FinalAnswerDecision


@dataclass(frozen=True)
class ExecutorContextContribution:
    """Read-only context text prepared outside the Executor loop."""

    content: str
    source: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.content, "content")
        require_non_empty_string(self.source, "source")


@dataclass(frozen=True)
class ExecutorMemoryContribution:
    """Read-only memory text prepared outside the Executor loop."""

    content: str
    source: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.content, "content")
        require_non_empty_string(self.source, "source")


@dataclass(frozen=True)
class ToolObservation:
    """Executor-owned safe projection of one post-Guardrail ToolResult."""

    step_index: int
    call_id: str
    tool_name: str
    status: ToolCallStatus
    output: dict[str, Any] | None = None
    error: ToolError | None = None
    evidence: tuple[ExecutionEvidence, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.step_index, int)
            or isinstance(self.step_index, bool)
            or self.step_index < 1
        ):
            raise ValueError("step_index must be a positive integer.")
        require_non_empty_string(self.call_id, "call_id")
        require_non_empty_string(self.tool_name, "tool_name")
        if not isinstance(self.status, ToolCallStatus):
            raise ValueError("status must be a ToolCallStatus.")
        if self.output is not None and not isinstance(self.output, dict):
            raise ValueError("output must be a dict when provided.")
        if self.error is not None and not isinstance(self.error, ToolError):
            raise ValueError("error must be a ToolError when provided.")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, ExecutionEvidence) for item in self.evidence
        ):
            raise ValueError("evidence must contain ExecutionEvidence values.")
        if self.status == ToolCallStatus.SUCCEEDED and self.error is not None:
            raise ValueError("a succeeded observation must not contain an error.")
        if self.status == ToolCallStatus.FAILED and self.error is None:
            raise ValueError("a failed observation must contain an error.")

    @classmethod
    def from_tool_result(
        cls, *, step_index: int, result: ToolResult
    ) -> "ToolObservation":
        if not isinstance(result, ToolResult):
            raise ValueError("result must be a ToolResult.")
        return cls(
            step_index=step_index,
            call_id=result.call_id,
            tool_name=result.tool_name,
            status=result.status,
            output=result.output,
            error=result.error,
            evidence=result.evidence,
        )


@dataclass(frozen=True)
class ExecutorModelInput:
    """Typed, request-local input rebuilt for each model decision."""

    request: RuntimeRequest
    prompt_contributions: tuple[PromptContribution, ...] = field(
        default_factory=tuple
    )
    context_contributions: tuple[ExecutorContextContribution, ...] = field(
        default_factory=tuple
    )
    memory_contributions: tuple[ExecutorMemoryContribution, ...] = field(
        default_factory=tuple
    )
    tool_catalog: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    observations: tuple[ToolObservation, ...] = field(default_factory=tuple)
    step_index: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.request, RuntimeRequest):
            raise ValueError("request must be a RuntimeRequest.")
        _require_tuple_of(
            self.prompt_contributions,
            PromptContribution,
            "prompt_contributions",
        )
        _require_tuple_of(
            self.context_contributions,
            ExecutorContextContribution,
            "context_contributions",
        )
        _require_tuple_of(
            self.memory_contributions,
            ExecutorMemoryContribution,
            "memory_contributions",
        )
        if not isinstance(self.tool_catalog, tuple) or any(
            not isinstance(item, dict) for item in self.tool_catalog
        ):
            raise ValueError("tool_catalog must contain dict values.")
        _require_tuple_of(self.observations, ToolObservation, "observations")
        if (
            not isinstance(self.step_index, int)
            or isinstance(self.step_index, bool)
            or self.step_index < 1
        ):
            raise ValueError("step_index must be a positive integer.")


def _require_tuple_of(values: object, item_type: type, field_name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, item_type) for item in values
    ):
        raise ValueError(f"{field_name} must contain {item_type.__name__} values.")


_STATUS_BY_STOP_REASON = {
    ExecutorStopReason.FINAL_ANSWER: ExecutorStatus.COMPLETED,
    ExecutorStopReason.CONFIRMATION_REQUIRED: ExecutorStatus.STOPPED,
    ExecutorStopReason.LIMIT_REACHED: ExecutorStatus.STOPPED,
    ExecutorStopReason.SAFETY_DENIED: ExecutorStatus.STOPPED,
    ExecutorStopReason.MODEL_FAILED: ExecutorStatus.FAILED,
    ExecutorStopReason.INVALID_MODEL_ACTION: ExecutorStatus.FAILED,
    ExecutorStopReason.INPUT_PROVIDER_FAILED: ExecutorStatus.FAILED,
    ExecutorStopReason.EXECUTOR_INTERNAL_FAILED: ExecutorStatus.FAILED,
}


@dataclass(frozen=True)
class ExecutorResult:
    """Stable structured result returned to Runtime or a future Planner."""

    run_id: str
    status: ExecutorStatus
    stop_reason: ExecutorStopReason
    final_message: str | None
    step_count: int
    observations: tuple[ToolObservation, ...] = field(default_factory=tuple)
    last_tool_result: ToolResult | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_string(self.run_id, "run_id")
        if not isinstance(self.status, ExecutorStatus):
            raise ValueError("status must be an ExecutorStatus.")
        if not isinstance(self.stop_reason, ExecutorStopReason):
            raise ValueError("stop_reason must be an ExecutorStopReason.")
        if _STATUS_BY_STOP_REASON[self.stop_reason] != self.status:
            raise ValueError("status must match stop_reason.")
        if self.status == ExecutorStatus.COMPLETED:
            if self.final_message is None:
                raise ValueError("completed result must contain final_message.")
            require_non_empty_string(self.final_message, "final_message")
        elif self.final_message is not None:
            raise ValueError("only a completed result may contain final_message.")
        if (
            not isinstance(self.step_count, int)
            or isinstance(self.step_count, bool)
            or self.step_count < 0
        ):
            raise ValueError("step_count must be a non-negative integer.")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, ToolObservation) for item in self.observations
        ):
            raise ValueError("observations must contain ToolObservation values.")
        if self.last_tool_result is not None and not isinstance(
            self.last_tool_result, ToolResult
        ):
            raise ValueError("last_tool_result must be a ToolResult when provided.")
        if self.error_code is not None:
            require_non_empty_string(self.error_code, "error_code")


ExecutorFeedbackItem = ToolObservation | ExecutorResult
