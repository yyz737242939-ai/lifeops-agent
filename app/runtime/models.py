"""Runtime request and result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from app.common.ids import new_id
from app.common.time import utc_now_iso


class RuntimeStatus(StrEnum):
    """High-level lifecycle status for one runtime request."""

    OK = "ok"
    ERROR = "error"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class RuntimeRequest:
    """Structured input for one runtime run."""

    user_input: str
    session_id: str
    turn_id: str = field(default_factory=lambda: new_id("turn"))
    run_id: str = field(default_factory=lambda: new_id("run"))
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.user_input.strip():
            raise ValueError("user_input must be non-empty.")
        if not self.session_id.strip():
            raise ValueError("session_id must be non-empty.")
        if not self.turn_id.strip():
            raise ValueError("turn_id must be non-empty.")
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty.")
        if not self.created_at.strip():
            raise ValueError("created_at must be non-empty.")


@dataclass(frozen=True)
class RuntimeResult:
    """Structured output for one runtime run."""

    run_id: str
    session_id: str
    status: RuntimeStatus
    message: str
    tool_result: dict[str, object] | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty.")
        if not self.session_id.strip():
            raise ValueError("session_id must be non-empty.")
        if not self.message.strip():
            raise ValueError("message must be non-empty.")
        if self.tool_result is not None and not isinstance(self.tool_result, dict):
            raise ValueError("tool_result must be a dict when provided.")
        if self.error_code is not None and not self.error_code.strip():
            raise ValueError("error_code must be non-empty when provided.")
