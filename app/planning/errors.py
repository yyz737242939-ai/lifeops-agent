"""Stable expected errors for Plan-and-Execute."""

from app.common.errors import AppError, StorageError


class PlanningError(AppError):
    """Base error for expected planning failures."""


class PlanningRouteError(PlanningError):
    """Raised when the planning route cannot be decided safely."""


class PlanContractError(PlanningError):
    """Raised when a plan violates the public planning contract."""


class PlanLifecycleError(PlanningError):
    """Raised when a plan lifecycle transition is not allowed."""


class PlanRepositoryError(StorageError):
    """Raised when persisted plan state cannot be read or changed safely."""
