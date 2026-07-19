"""Shared project error types."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base error for expected LifeOps runtime failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class StorageError(AppError):
    """Raised when storage operations fail."""


class ConfigError(AppError):
    """Raised when application configuration is invalid."""


class MigrationError(StorageError):
    """Raised when SQLite schema migration fails."""


class SerializationError(AppError):
    """Raised when JSON serialization or parsing fails."""
