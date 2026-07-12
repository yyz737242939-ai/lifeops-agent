"""Expected Tool System failures."""

from app.common.errors import AppError


class ToolSystemError(AppError):
    """Base error for expected Tool System failures."""


class ToolRegistryError(ToolSystemError):
    """Raised when Tool registry contents or operations are invalid."""


class ToolNotFoundError(ToolRegistryError):
    """Raised when a requested Tool is not registered."""


class ToolSchemaError(ToolRegistryError):
    """Raised when a Tool schema violates the supported JSON Schema subset."""


class ToolAuthorizationError(ToolSystemError):
    """Raised when request-local allowed Tools cannot be resolved safely."""


class ToolGatewayError(ToolSystemError):
    """Raised when the Tool Gateway receives an invalid execution contract."""
