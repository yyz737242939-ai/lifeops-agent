"""Application log configuration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class TraceSink(Protocol):
    """Application-owned sink for ordered request-local events."""

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """Append one event at the point where it occurs."""

        ...


class LlmInteractionSink(Protocol):
    """Request-local sink for ordered provider request/response records."""

    def record(
        self,
        *,
        provider: str,
        model: str,
        request: dict[str, Any],
        response: dict[str, Any] | None,
        status: str = "ok",
        error_code: str | None = None,
    ) -> None:
        ...


class OptionalLogAppender:
    """Wrap an optional log callback behind a stable append method."""

    def __init__(
        self,
        callback: Callable[[str, dict[str, Any] | None], None] | None,
    ) -> None:
        self._callback = callback

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        if self._callback is None:
            return
        self._callback(event_type, payload)


def ensure_application_logger() -> logging.Logger:
    """Return the base app logger without leaking to the root logger."""

    logger = logging.getLogger("lifeops")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def configure_application_logging(session_dir: str | Path) -> Path:
    """Route application diagnostics to exactly one active session file."""

    log_path = Path(session_dir) / "application.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = ensure_application_logger()
    resolved = str(log_path.resolve())

    for handler in list(logger.handlers):
        if not isinstance(handler, logging.FileHandler):
            continue
        if handler.baseFilename == resolved:
            return log_path
        logger.removeHandler(handler)
        handler.close()

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return log_path


def close_application_logging() -> None:
    """Close the active session FileHandler, if one is configured."""

    logger = ensure_application_logger()
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()
