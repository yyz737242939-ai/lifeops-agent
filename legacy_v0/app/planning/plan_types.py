"""Transient Plan and Execute v0 data models."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.time import now_iso, timestamp_id


PlanStatus = Literal[
    "pending_confirmation",
    "active",
    "completed",
    "blocked",
    "cancelled",
    "superseded",
    "expired",
]
PlanStepStatus = Literal[
    "pending",
    "in_progress",
    "done",
    "blocked",
    "skipped",
    "failed",
]
PlanStepRiskLevel = Literal["low", "medium", "high"]

TERMINAL_PLAN_STATUSES: set[PlanStatus] = {
    "completed",
    "blocked",
    "cancelled",
    "superseded",
    "expired",
}
TERMINAL_STEP_STATUSES: set[PlanStepStatus] = {
    "done",
    "blocked",
    "skipped",
    "failed",
}


def next_plan_id() -> str:
    return f"plan_{timestamp_id()}"


def next_plan_step_id() -> str:
    return f"plan_step_{timestamp_id()}"


class PlanStep(BaseModel):
    """One transient step in a Plan and Execute run."""

    step_id: str = Field(default_factory=next_plan_step_id)
    title: str
    intent: str
    status: PlanStepStatus = "pending"
    requires_user_confirmation: bool = False
    risk_level: PlanStepRiskLevel = "low"
    expected_tool_domain: str | None = None
    last_run_id: str | None = None
    last_result_summary: str | None = None
    blocker: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("step_id", "title", "intent")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Plan step id, title and intent cannot be empty")
        return clean_value

    @field_validator(
        "expected_tool_domain",
        "last_run_id",
        "last_result_summary",
        "blocker",
    )
    @classmethod
    def optional_text_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STEP_STATUSES

    def start(self) -> None:
        self._ensure_not_terminal()
        self.status = "in_progress"
        self.updated_at = now_iso()

    def mark_done(
        self,
        *,
        last_run_id: str | None = None,
        result_summary: str | None = None,
    ) -> None:
        self._ensure_not_terminal()
        self.status = "done"
        self.last_run_id = self._clean_optional_text(last_run_id)
        self.last_result_summary = self._clean_optional_text(result_summary)
        self.blocker = None
        self.updated_at = now_iso()

    def mark_blocked(self, blocker: str) -> None:
        self._ensure_not_terminal()
        clean_blocker = blocker.strip()
        if not clean_blocker:
            raise ValueError("Plan step blocker cannot be empty")
        self.status = "blocked"
        self.blocker = clean_blocker
        self.updated_at = now_iso()

    def mark_failed(self, summary: str | None = None) -> None:
        self._ensure_not_terminal()
        self.status = "failed"
        self.last_result_summary = self._clean_optional_text(summary)
        self.updated_at = now_iso()

    def skip(self, summary: str | None = None) -> None:
        self._ensure_not_terminal()
        self.status = "skipped"
        self.last_result_summary = self._clean_optional_text(summary)
        self.updated_at = now_iso()

    def _ensure_not_terminal(self) -> None:
        if self.is_terminal:
            raise RuntimeError("Plan step is already terminal")

    @staticmethod
    def _clean_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None


class PlanRun(BaseModel):
    """A transient execution plan held in the current Agent instance."""

    plan_id: str = Field(default_factory=next_plan_id)
    goal: str
    status: PlanStatus = "pending_confirmation"
    steps: list[PlanStep]
    current_step_id: str | None = None
    source_user_input_summary: str
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("plan_id", "goal", "source_user_input_summary")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Plan id, goal and source summary cannot be empty")
        return clean_value

    @field_validator("current_step_id")
    @classmethod
    def optional_text_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None

    @model_validator(mode="after")
    def plan_must_have_steps_and_valid_current_step(self) -> "PlanRun":
        if not self.steps:
            raise ValueError("Plan must contain at least one step")
        if self.current_step_id is not None and self._find_step(self.current_step_id) is None:
            raise ValueError("current_step_id must reference an existing plan step")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_PLAN_STATUSES

    @property
    def current_step(self) -> PlanStep | None:
        if self.current_step_id is None:
            return None
        return self._find_step(self.current_step_id)

    def confirm(self) -> PlanStep:
        if self.status != "pending_confirmation":
            raise RuntimeError("Only pending plans can be confirmed")
        step = self._first_executable_step()
        if step is None:
            raise RuntimeError("Plan has no executable steps")
        self.status = "active"
        self.current_step_id = step.step_id
        self._touch()
        return step

    def cancel(self) -> None:
        self._ensure_not_terminal()
        self.status = "cancelled"
        self.current_step_id = None
        self._touch()

    def supersede(self) -> None:
        self._ensure_not_terminal()
        self.status = "superseded"
        self.current_step_id = None
        self._touch()

    def expire(self) -> None:
        if self.status != "pending_confirmation":
            raise RuntimeError("Only pending plans can expire")
        self.status = "expired"
        self.current_step_id = None
        self._touch()

    def select_current_step(self, step_id: str) -> PlanStep:
        self._ensure_active()
        step = self._require_step(step_id)
        if step.is_terminal:
            raise RuntimeError("Cannot select a terminal plan step")
        self.current_step_id = step.step_id
        self._touch()
        return step

    def start_current_step(self) -> PlanStep:
        step = self._require_current_step()
        step.start()
        self._touch()
        return step

    def mark_current_step_done(
        self,
        *,
        last_run_id: str | None = None,
        result_summary: str | None = None,
    ) -> PlanStep:
        step = self._require_current_step()
        step.mark_done(last_run_id=last_run_id, result_summary=result_summary)
        self._advance_after_terminal_step()
        self._touch()
        return step

    def mark_current_step_blocked(self, blocker: str) -> PlanStep:
        step = self._require_current_step()
        step.mark_blocked(blocker)
        self.status = "blocked"
        self.current_step_id = None
        self._touch()
        return step

    def mark_current_step_failed(self, summary: str | None = None) -> PlanStep:
        step = self._require_current_step()
        step.mark_failed(summary)
        self.current_step_id = None
        self._touch()
        return step

    def skip_current_step(self, summary: str | None = None) -> PlanStep:
        step = self._require_current_step()
        step.skip(summary)
        self._advance_after_terminal_step()
        self._touch()
        return step

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, value: dict) -> "PlanRun":
        return cls.model_validate(value)

    def _advance_after_terminal_step(self) -> None:
        next_step = self._first_executable_step()
        if next_step is None:
            self.status = "completed"
            self.current_step_id = None
            return
        self.current_step_id = next_step.step_id

    def _ensure_active(self) -> None:
        if self.status != "active":
            raise RuntimeError("Plan is not active")

    def _ensure_not_terminal(self) -> None:
        if self.is_terminal:
            raise RuntimeError("Plan is already terminal")

    def _require_current_step(self) -> PlanStep:
        self._ensure_active()
        if self.current_step_id is None:
            raise RuntimeError("Plan has no current step")
        return self._require_step(self.current_step_id)

    def _find_step(self, step_id: str) -> PlanStep | None:
        return next((step for step in self.steps if step.step_id == step_id), None)

    def _require_step(self, step_id: str) -> PlanStep:
        step = self._find_step(step_id)
        if step is None:
            raise ValueError("Unknown plan step")
        return step

    def _first_executable_step(self) -> PlanStep | None:
        for step in self.steps:
            if not step.is_terminal:
                return step
        return None

    def _touch(self) -> None:
        self.updated_at = now_iso()
