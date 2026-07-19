"""Narrow storage ports for Execution Feedback and read-only Recovery."""

from __future__ import annotations

from typing import Protocol

from app.recovery.models import ExecutionFeedback


class ExecutionFeedbackRepository(Protocol):
    def save(self, feedback: ExecutionFeedback) -> None: ...

    def get_for_run(self, session_id: str, run_id: str) -> ExecutionFeedback: ...

    def get_latest(self, session_id: str) -> ExecutionFeedback | None: ...
