"""Stable errors for pure Execution Feedback construction."""

from __future__ import annotations

from app.common.validation import require_non_empty_string
from app.common.errors import StorageError


RECOVERY_SOURCE_UNAVAILABLE = "recovery_source_unavailable"
RECOVERY_SOURCE_CONFLICT = "recovery_source_conflict"
RECOVERY_EXPLAINER_FAILED = "recovery_explainer_failed"


class ExecutionFeedbackBuildError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        require_non_empty_string(message, "message")
        require_non_empty_string(code, "code")
        super().__init__(message)
        self.code = code


class ExecutionFeedbackRepositoryError(StorageError):
    """Raised when canonical feedback cannot be stored or reconstructed."""


class ExecutionFeedbackCollectionError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        require_non_empty_string(message, "message")
        require_non_empty_string(code, "code")
        super().__init__(message)
        self.code = code
