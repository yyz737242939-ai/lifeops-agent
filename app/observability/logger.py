"""Application log configuration."""

from __future__ import annotations

import logging
from pathlib import Path


def ensure_application_logger() -> logging.Logger:
    """Return the base app logger without leaking to the root logger."""

    logger = logging.getLogger("lifeops")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def configure_application_logging(session_dir: str | Path) -> Path:
    """Configure a plain application.log file without duplicate handlers."""

    log_path = Path(session_dir) / "application.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = ensure_application_logger()
    resolved = str(log_path.resolve())

    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == resolved:
            return log_path

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return log_path
