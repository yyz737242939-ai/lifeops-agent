"""Stable expected failures for Stage 9B Long-term Memory."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.common.errors import AppError


class MemoryErrorCode(StrEnum):
    INVALID = "memory_invalid"
    PATH_INVALID = "memory_path_invalid"
    FILE_WRITE_FAILED = "memory_file_write_failed"
    FILE_READ_FAILED = "memory_file_read_failed"
    FILE_MISSING = "memory_file_missing"
    HASH_MISMATCH = "memory_hash_mismatch"
    INDEX_FAILED = "memory_index_failed"
    NOT_FOUND = "memory_not_found"
    VERSION_CONFLICT = "memory_version_conflict"
    ALREADY_ARCHIVED = "memory_already_archived"


class MemoryError(AppError):
    def __init__(
        self,
        message: str,
        *,
        code: MemoryErrorCode,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(code, MemoryErrorCode):
            raise ValueError("code must be a MemoryErrorCode.")
        super().__init__(message, code=code.value, details=details)


class MemoryContractError(MemoryError):
    """Raised when typed Memory input violates the frozen contract."""


class MemoryRepositoryError(MemoryError):
    """Raised when committed Memory index state cannot be read or changed."""


class MemoryDocumentStoreError(MemoryError):
    """Raised when immutable Memory content cannot be stored or verified."""
