"""Persistent recovery data models for cross-process Agent run records."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.time import now_iso, timestamp_id


RecoveryRunStatus = Literal[
    "running",
    "completed",
    "partial",
    "failed",
    "stopped",
    "interrupted",
]
RecoveryActionStatus = Literal[
    "completed",
    "failed",
    "skipped",
]
RecoveryActionEffect = Literal["read", "write"]


def next_recovery_action_id() -> str:
    return f"action_{timestamp_id()}"


class PersistentActionRecord(BaseModel):
    """JSON-safe summary of one tool action inside a persisted run record."""

    action_id: str = Field(default_factory=next_recovery_action_id)
    run_id: str
    call_id: str
    tool_name: str
    arguments_hash: str
    arguments_preview: dict[str, Any] = Field(default_factory=dict)
    status: RecoveryActionStatus
    effect: RecoveryActionEffect
    idempotency_key: str | None = None
    result_summary: str | None = None
    error_summary: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator(
        "action_id",
        "run_id",
        "call_id",
        "tool_name",
        "arguments_hash",
    )
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Persistent action identifiers cannot be empty")
        return clean_value

    @field_validator(
        "idempotency_key",
        "result_summary",
        "error_summary",
    )
    @classmethod
    def optional_text_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PersistentActionRecord":
        return cls.model_validate(value)


class RunRecord(BaseModel):
    """Persistent summary of one Agent.chat() run for recovery prompts."""

    run_id: str
    status: RecoveryRunStatus
    started_at: str = Field(default_factory=now_iso)
    ended_at: str | None = None
    stop_reason: str | None = None
    task_id: str | None = None
    user_input_summary: str
    last_successful_action: PersistentActionRecord | None = None
    last_failed_action: PersistentActionRecord | None = None
    action_count: int = 0
    actions: list[PersistentActionRecord] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @field_validator("run_id", "user_input_summary")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Run record id and summary cannot be empty")
        return clean_value

    @field_validator("ended_at", "stop_reason", "task_id")
    @classmethod
    def optional_text_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None

    @field_validator("action_count")
    @classmethod
    def action_count_must_not_be_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("action_count cannot be negative")
        return value

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunRecord":
        return cls.model_validate(value)
