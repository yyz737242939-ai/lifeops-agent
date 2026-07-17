"""Stable expected failures for Context assembly and conversation storage."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.common.errors import AppError


class ContextErrorCode(StrEnum):
    """Content-free codes safe for reports, events, and runtime results."""

    INPUT_TOO_LARGE = "context_input_too_large"
    SESSION_INVALID = "context_session_invalid"
    PATH_INVALID = "context_path_invalid"
    TURN_APPEND_FAILED = "conversation_turn_append_failed"
    HISTORY_READ_FAILED = "conversation_history_read_failed"
    CORRUPT_TAIL = "conversation_corrupt_tail"
    SEQUENCE_INVALID = "conversation_sequence_invalid"
    SUMMARY_PROVIDER_FAILED = "context_summary_provider_failed"
    SUMMARY_INVALID = "context_summary_invalid"
    SUMMARY_TOO_LARGE = "context_summary_too_large"
    PROFILE_PROVIDER_FAILED = "context_profile_provider_failed"
    MEMORY_PROVIDER_FAILED = "context_memory_provider_failed"
    ASSEMBLY_FAILED = "context_assembly_failed"
    CONVERSATION_PERSIST_FAILED = "conversation_persist_failed"


class ContextError(AppError):
    """Base error carrying one frozen Context error code."""

    def __init__(
        self,
        message: str,
        *,
        code: ContextErrorCode,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(code, ContextErrorCode):
            raise ValueError("code must be a ContextErrorCode.")
        super().__init__(message, code=code.value, details=details)


class ContextContractError(ContextError):
    """Raised when Context input or output violates a frozen contract."""


class ConversationRepositoryError(ContextError):
    """Raised when session conversation files cannot be used safely."""


class ContextProviderError(ContextError):
    """Raised when a summarizer, Profile, or Memory provider fails safely."""
