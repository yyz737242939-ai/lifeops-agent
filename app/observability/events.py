"""Runtime trace and LLM interaction event models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.common.ids import new_id
from app.common.time import utc_now_iso


@dataclass(frozen=True)
class LogRuntimeEvent:
    run_id: str
    seq: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("logevt"))
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty.")
        if self.seq < 1:
            raise ValueError("seq must be greater than zero.")
        if not self.event_type.strip():
            raise ValueError("event_type must be non-empty.")


@dataclass(frozen=True)
class LogTraceEvent(LogRuntimeEvent):
    """Structured runtime trace event with a compact payload."""


@dataclass(frozen=True)
class LogLlmInteraction:
    """Raw LLM request-response log model."""

    run_id: str
    seq: int
    request: dict[str, Any]
    provider: str | None = None
    model: str | None = None
    response: dict[str, Any] | None = None
    status: str = "ok"
    error_code: str | None = None
    id: str = field(default_factory=lambda: new_id("logllm"))
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must be non-empty.")
        if self.seq < 1:
            raise ValueError("seq must be greater than zero.")
        if not isinstance(self.request, dict):
            raise ValueError("request must be a dict.")
        if self.response is not None and not isinstance(self.response, dict):
            raise ValueError("response must be a dict when provided.")
        if not self.status.strip():
            raise ValueError("status must be non-empty.")
