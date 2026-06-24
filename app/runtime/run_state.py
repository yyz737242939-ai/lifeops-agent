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
    tool_call_signature: str | None = None
    tool_observation_signature: str | None = None
    tool_execution_attempt_count: int = 1
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "tool_call_signature": self.tool_call_signature,
            "tool_observation_signature": self.tool_observation_signature,
            "tool_execution_attempt_count": self.tool_execution_attempt_count,
            "idempotency_key": self.idempotency_key,
        }


@dataclass
class RunState:
    """Mutable execution state scoped to exactly one Agent.chat() call."""

    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex}")
    status: RunStatus = RunStatus.RUNNING
    chat_llm_round_count: int = 0
    chat_tool_execution_attempt_count: int = 0
    action_records: list[ActionRecord] = field(default_factory=list)
    stop_reason: StopReason | None = None
    chat_llm_request_count: int = 0
    chat_retry_counts_by_operation: dict[str, int] = field(default_factory=dict)
    tool_call_signature_counts: dict[str, int] = field(default_factory=dict)
    tool_observation_signature_counts: dict[str, int] = field(default_factory=dict)
    recent_tool_call_signatures: list[str] = field(default_factory=list)
    chat_cancellation_requested: bool = False

    @property
    def completed_action_records(self) -> list[ActionRecord]:
        return [
            action
            for action in self.action_records
            if action.status == ActionStatus.COMPLETED
        ]

    @property
    def failed_action_records(self) -> list[ActionRecord]:
        return [
            action
            for action in self.action_records
            if action.status == ActionStatus.FAILED
        ]

    @property
    def skipped_action_records(self) -> list[ActionRecord]:
        return [
            action
            for action in self.action_records
            if action.status == ActionStatus.SKIPPED
        ]

    def can_start_llm_round(self, limits: LoopLimits) -> bool:
        return (
            self.status == RunStatus.RUNNING
            and self.chat_llm_round_count < limits.max_llm_rounds
        )

    def start_llm_round(self, limits: LoopLimits) -> int:
        if not self.can_start_llm_round(limits):
            raise RuntimeError("LLM round budget exhausted")
        self.chat_llm_round_count += 1
        return self.chat_llm_round_count

    def start_llm_request(self) -> int:
        self._ensure_running()
        self.chat_llm_request_count += 1
        return self.chat_llm_request_count

    def can_start_tool_call(
        self,
        limits: LoopLimits,
        *,
        calls_started_this_round: int,
    ) -> bool:
        return (
            self.status == RunStatus.RUNNING
            and calls_started_this_round < limits.max_tool_calls_per_round
            and self.chat_tool_execution_attempt_count < limits.max_total_tool_calls
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
        self.chat_tool_execution_attempt_count += 1

    def add_action(self, action: ActionRecord) -> None:
        if self.status != RunStatus.RUNNING:
            raise RuntimeError("Cannot add an action to a terminal run")
        self.action_records.append(action)

    def register_call(self, tool_name: str, arguments: Any) -> tuple[str, int, bool]:
        signature = stable_signature({"tool": tool_name, "arguments": arguments})
        count = self.tool_call_signature_counts.get(signature, 0) + 1
        self.tool_call_signature_counts[signature] = count
        cycle_detected = (
            len(self.recent_tool_call_signatures) >= 3
            and self.recent_tool_call_signatures[-3]
            == self.recent_tool_call_signatures[-1]
            and self.recent_tool_call_signatures[-2] == signature
        )
        self.recent_tool_call_signatures.append(signature)
        return signature, count, cycle_detected

    def register_observation(self, call_signature: str, result: Any) -> tuple[str, int]:
        signature = stable_signature(
            {"call_signature": call_signature, "result": result}
        )
        count = self.tool_observation_signature_counts.get(signature, 0) + 1
        self.tool_observation_signature_counts[signature] = count
        return signature, count

    def record_retry(self, key: str) -> int:
        count = self.chat_retry_counts_by_operation.get(key, 0) + 1
        self.chat_retry_counts_by_operation[key] = count
        return count

    def request_cancel(self) -> None:
        if self.status == RunStatus.RUNNING:
            self.chat_cancellation_requested = True

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
            "state_scope": "single_agent_chat",
            "run_id": self.run_id,
            "status": self.status.value,
            "chat_llm_round_count": self.chat_llm_round_count,
            "chat_llm_request_count": self.chat_llm_request_count,
            "chat_tool_execution_attempt_count": (
                self.chat_tool_execution_attempt_count
            ),
            "chat_completed_action_count": len(self.completed_action_records),
            "chat_failed_action_count": len(self.failed_action_records),
            "chat_skipped_action_count": len(self.skipped_action_records),
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "chat_retry_counts_by_operation": dict(
                self.chat_retry_counts_by_operation
            ),
            "chat_cancellation_requested": self.chat_cancellation_requested,
        }
        if include_actions:
            result["action_records"] = [
                action.to_dict() for action in self.action_records
            ]
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
