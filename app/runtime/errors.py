from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorType(StrEnum):
    """Categories that drive correction, retry, or stop behavior."""

    CONTROL = "control"
    INVALID_ARGUMENTS = "invalid_arguments"
    BUSINESS_ERROR = "business_error"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    TRANSIENT_ERROR = "transient_error"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ExecutionError:
    """Normalized error contract shared by Tool and LLM paths."""

    type: ErrorType
    code: str
    message: str
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


_KNOWN_TOOL_ERRORS: dict[str, tuple[ErrorType, bool]] = {
    "invalid_json_arguments": (ErrorType.INVALID_ARGUMENTS, False),
    "invalid_arguments": (ErrorType.INVALID_ARGUMENTS, False),
    "invalid_date": (ErrorType.INVALID_ARGUMENTS, False),
    "budget_not_found": (ErrorType.BUSINESS_ERROR, False),
    "todo_not_found": (ErrorType.NOT_FOUND, False),
    "context_ref_not_found": (ErrorType.NOT_FOUND, False),
    "tool_not_found": (ErrorType.NOT_FOUND, False),
    "tool_not_allowed": (ErrorType.PERMISSION_DENIED, False),
    "tool_timeout": (ErrorType.TIMEOUT, True),
    "tool_failed": (ErrorType.INTERNAL_ERROR, False),
}


def error_result(
    action: str,
    error: ExecutionError,
    **fields: Any,
) -> dict[str, Any]:
    """Wrap an ExecutionError in the standard failed-result envelope."""
    return {
        "ok": False,
        "action": action,
        "error": error.to_dict(),
        **fields,
    }


def normalize_tool_result(action: str, result: dict[str, Any]) -> dict[str, Any]:
    """Normalize failed tool returns into the structured error contract."""
    if result.get("ok") is not False:
        return result

    raw_error = result.get("error")
    if isinstance(raw_error, dict):
        return result

    code = str(raw_error or "tool_failed")
    error_type, retryable = _KNOWN_TOOL_ERRORS.get(
        code,
        (ErrorType.BUSINESS_ERROR, False),
    )
    normalized = dict(result)
    normalized["error"] = ExecutionError(
        type=error_type,
        code=code,
        message=str(result.get("message") or code.replace("_", " ")),
        retryable=retryable,
    ).to_dict()
    return normalized


def tool_error_from_result(result: dict[str, Any] | None) -> ExecutionError | None:
    """Recover a typed error from a normalized failed tool result."""
    if not isinstance(result, dict) or result.get("ok") is not False:
        return None
    raw_error = result.get("error")
    if not isinstance(raw_error, dict):
        return None
    try:
        return ExecutionError(
            type=ErrorType(raw_error["type"]),
            code=str(raw_error["code"]),
            message=str(raw_error["message"]),
            retryable=bool(raw_error.get("retryable", False)),
        )
    except (KeyError, ValueError):
        return None


def classify_tool_exception(action: str, error: Exception) -> dict[str, Any]:
    """Convert Python exceptions into retry-aware tool errors."""
    if isinstance(error, TimeoutError):
        execution_error = ExecutionError(
            ErrorType.TIMEOUT,
            "tool_timeout",
            str(error) or f"{action} timed out",
            retryable=True,
        )
    elif isinstance(error, (TypeError, ValueError)):
        execution_error = ExecutionError(
            ErrorType.INVALID_ARGUMENTS,
            "invalid_arguments",
            str(error),
            retryable=False,
        )
    elif isinstance(error, (ConnectionError, OSError)):
        execution_error = ExecutionError(
            ErrorType.TRANSIENT_ERROR,
            "transient_tool_error",
            str(error),
            retryable=True,
        )
    else:
        execution_error = ExecutionError(
            ErrorType.INTERNAL_ERROR,
            "tool_failed",
            str(error),
            retryable=False,
        )
    return error_result(action, execution_error)


def classify_llm_exception(error: Exception) -> ExecutionError:
    """Classify provider failures without one SDK-specific exception tree."""
    class_name = type(error).__name__.lower()
    message = str(error)
    if "timeout" in class_name:
        return ExecutionError(ErrorType.TIMEOUT, "llm_timeout", message, True)
    if "ratelimit" in class_name or "rate_limit" in class_name:
        return ExecutionError(ErrorType.TRANSIENT_ERROR, "llm_rate_limit", message, True)
    if "connection" in class_name:
        return ExecutionError(
            ErrorType.TRANSIENT_ERROR,
            "llm_connection_error",
            message,
            True,
        )
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and status_code >= 500:
        return ExecutionError(
            ErrorType.TRANSIENT_ERROR,
            "llm_server_error",
            message,
            True,
        )
    return ExecutionError(ErrorType.INTERNAL_ERROR, "llm_request_failed", message, False)
