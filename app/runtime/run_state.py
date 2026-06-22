from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    STOPPED = "stopped"


class StopReason(StrEnum):
    COMPLETED = "completed"
    LLM_BUDGET_EXHAUSTED = "llm_budget_exhausted"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    LLM_REQUEST_FAILED = "llm_request_failed"


class ActionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class LoopLimits:
    max_llm_rounds: int = 5
    max_tool_calls_per_round: int = 10
    max_total_tool_calls: int = 50

    def __post_init__(self) -> None:
        for field_name in (
            "max_llm_rounds",
            "max_tool_calls_per_round",
            "max_total_tool_calls",
        ):
            if getattr(self, field_name) < 1:
                raise ValueError(f"{field_name} must be at least 1")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_llm_rounds": self.max_llm_rounds,
            "max_tool_calls_per_round": self.max_tool_calls_per_round,
            "max_total_tool_calls": self.max_total_tool_calls,
        }


@dataclass
class ActionRecord:
    call_id: str
    tool_name: str
    arguments: Any
    status: ActionStatus
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class RunState:
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex}")
    status: RunStatus = RunStatus.RUNNING
    llm_rounds: int = 0
    total_tool_calls: int = 0
    actions: list[ActionRecord] = field(default_factory=list)
    stop_reason: StopReason | None = None

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
            "completed_action_count": len(self.completed_actions),
            "failed_action_count": len(self.failed_actions),
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
        }
        if include_actions:
            result["actions"] = [action.to_dict() for action in self.actions]
        return result
