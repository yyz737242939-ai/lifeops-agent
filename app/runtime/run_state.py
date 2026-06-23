import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class RunStatus(StrEnum):
    """Terminal and in-progress states for one Agent chat request."""

    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    STOPPED = "stopped"


class StopReason(StrEnum):
    """Machine-readable reason the Runtime ended a run."""

    COMPLETED = "completed"
    LLM_BUDGET_EXHAUSTED = "llm_budget_exhausted"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    LLM_REQUEST_FAILED = "llm_request_failed"
    REPEATED_CALL = "repeated_call"
    NO_PROGRESS = "no_progress"
    CANCELLED = "cancelled"
    UNRECOVERABLE_ERROR = "unrecoverable_error"


class ActionStatus(StrEnum):
    """Outcome of one model-requested tool action."""

    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class LoopLimits:
    """Independent budgets for LLM rounds, tool attempts, and retries."""

    max_llm_rounds: int = 5
    max_tool_calls_per_round: int = 10
    max_total_tool_calls: int = 50
    max_tool_retries: int = 2
    max_llm_retries: int = 2
    max_same_call_attempts: int = 2
    max_identical_observations: int = 2
    retry_backoff_seconds: float = 0.2

    def __post_init__(self) -> None:
        for field_name in (
            "max_llm_rounds",
            "max_tool_calls_per_round",
            "max_total_tool_calls",
            "max_same_call_attempts",
            "max_identical_observations",
        ):
            if getattr(self, field_name) < 1:
                raise ValueError(f"{field_name} must be at least 1")

        for field_name in ("max_tool_retries", "max_llm_retries"):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be at least 0")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be at least 0")

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_llm_rounds": self.max_llm_rounds,
            "max_tool_calls_per_round": self.max_tool_calls_per_round,
            "max_total_tool_calls": self.max_total_tool_calls,
            "max_tool_retries": self.max_tool_retries,
            "max_llm_retries": self.max_llm_retries,
            "max_same_call_attempts": self.max_same_call_attempts,
            "max_identical_observations": self.max_identical_observations,
            "retry_backoff_seconds": self.retry_backoff_seconds,
        }


@dataclass
class ActionRecord:
    """In-memory account of one requested tool action."""

    call_id: str
    tool_name: str
    arguments: Any
    status: ActionStatus
    result: Any = None
    error: Any = None
    signature: str | None = None
    observation_signature: str | None = None
    attempt_count: int = 1
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "signature": self.signature,
            "observation_signature": self.observation_signature,
            "attempt_count": self.attempt_count,
            "idempotency_key": self.idempotency_key,
        }


@dataclass
class RunState:
    """Mutable execution state scoped to exactly one Agent.chat() call."""

    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex}")
    status: RunStatus = RunStatus.RUNNING
    llm_rounds: int = 0
    total_tool_calls: int = 0
    actions: list[ActionRecord] = field(default_factory=list)
    stop_reason: StopReason | None = None
    llm_attempts: int = 0
    retry_counts: dict[str, int] = field(default_factory=dict)
    call_signature_counts: dict[str, int] = field(default_factory=dict)
    observation_signature_counts: dict[str, int] = field(default_factory=dict)
    recent_call_signatures: list[str] = field(default_factory=list)
    cancel_requested: bool = False

    @property
    def completed_actions(self) -> list[ActionRecord]:
        return [
            action for action in self.actions if action.status == ActionStatus.COMPLETED
        ]

    @property
    def failed_actions(self) -> list[ActionRecord]:
        return [
            action for action in self.actions if action.status == ActionStatus.FAILED
        ]

    @property
    def skipped_actions(self) -> list[ActionRecord]:
        return [
            action for action in self.actions if action.status == ActionStatus.SKIPPED
        ]

    def can_start_llm_round(self, limits: LoopLimits) -> bool:
        return (
            self.status == RunStatus.RUNNING
            and self.llm_rounds < limits.max_llm_rounds
        )

    def start_llm_round(self, limits: LoopLimits) -> int:
        if not self.can_start_llm_round(limits):
            raise RuntimeError("LLM round budget exhausted")
        self.llm_rounds += 1
        return self.llm_rounds

    def start_llm_attempt(self) -> int:
        self._ensure_running()
        self.llm_attempts += 1
        return self.llm_attempts

    def can_start_tool_call(
        self,
        limits: LoopLimits,
        *,
        calls_started_this_round: int,
    ) -> bool:
        return (
            self.status == RunStatus.RUNNING
            and calls_started_this_round < limits.max_tool_calls_per_round
            and self.total_tool_calls < limits.max_total_tool_calls
        )

    def start_tool_call(
        self,
        limits: LoopLimits,
        *,
        calls_started_this_round: int,
    ) -> None:
        if not self.can_start_tool_call(
            limits,
            calls_started_this_round=calls_started_this_round,
        ):
            raise RuntimeError("Tool call budget exhausted")
        self.total_tool_calls += 1

    def add_action(self, action: ActionRecord) -> None:
        if self.status != RunStatus.RUNNING:
            raise RuntimeError("Cannot add an action to a terminal run")
        self.actions.append(action)

    def register_call(self, tool_name: str, arguments: Any) -> tuple[str, int, bool]:
        signature = stable_signature({"tool": tool_name, "arguments": arguments})
        count = self.call_signature_counts.get(signature, 0) + 1
        self.call_signature_counts[signature] = count
        cycle_detected = (
            len(self.recent_call_signatures) >= 3
            and self.recent_call_signatures[-3] == self.recent_call_signatures[-1]
            and self.recent_call_signatures[-2] == signature
        )
        self.recent_call_signatures.append(signature)
        return signature, count, cycle_detected

    def register_observation(self, call_signature: str, result: Any) -> tuple[str, int]:
        signature = stable_signature(
            {"call_signature": call_signature, "result": result}
        )
        count = self.observation_signature_counts.get(signature, 0) + 1
        self.observation_signature_counts[signature] = count
        return signature, count

    def record_retry(self, key: str) -> int:
        count = self.retry_counts.get(key, 0) + 1
        self.retry_counts[key] = count
        return count

    def request_cancel(self) -> None:
        if self.status == RunStatus.RUNNING:
            self.cancel_requested = True

    def complete(self) -> None:
        self._ensure_running()
        self.status = RunStatus.COMPLETED
        self.stop_reason = StopReason.COMPLETED

    def stop(self, reason: StopReason, *, partial: bool = False) -> None:
        self._ensure_running()
        self.status = RunStatus.PARTIAL if partial else RunStatus.STOPPED
        self.stop_reason = reason

    def fail(self, reason: StopReason) -> None:
        self._ensure_running()
        self.status = RunStatus.FAILED
        self.stop_reason = reason

    def _ensure_running(self) -> None:
        if self.status != RunStatus.RUNNING:
            raise RuntimeError("Run is already in a terminal state")

    def to_dict(self, *, include_actions: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status.value,
            "llm_rounds": self.llm_rounds,
            "total_tool_calls": self.total_tool_calls,
            "llm_attempts": self.llm_attempts,
            "completed_action_count": len(self.completed_actions),
            "failed_action_count": len(self.failed_actions),
            "skipped_action_count": len(self.skipped_actions),
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "retry_counts": dict(self.retry_counts),
            "cancel_requested": self.cancel_requested,
        }
        if include_actions:
            result["actions"] = [action.to_dict() for action in self.actions]
        return result


def stable_signature(value: Any) -> str:
    """Hash normalized JSON so checks ignore dictionary key order."""
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
