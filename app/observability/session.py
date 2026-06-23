import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.observability.serialization import json_safe


LOG_ROOT = Path(__file__).resolve().parents[2] / "logs" / "sessions"

_lock = threading.RLock()
_session_id: str | None = None
_session_dir: Path | None = None
_started_at: str | None = None


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def start_logging_session() -> dict[str, Path]:
    """Start a fresh process-level log session and create its three channels."""
    global _session_dir, _session_id, _started_at

    with _lock:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        _session_id = f"session_{timestamp}"
        _session_dir = LOG_ROOT / _session_id
        _session_dir.mkdir(parents=True, exist_ok=True)
        _started_at = now_iso()

        metadata = {
            "session_id": _session_id,
            "started_at": _started_at,
            "format_version": 2,
            "channels": ["events", "llm", "application"],
        }
        (_session_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for filename in ("events.jsonl", "llm.jsonl", "application.log"):
            (_session_dir / filename).touch(exist_ok=True)
        _configure_application_handler(_session_dir / "application.log")
        return current_session_files()


def close_logging_session() -> None:
    """Flush handlers and release session files, primarily for clean shutdown/tests."""
    global _session_dir, _session_id, _started_at
    with _lock:
        logger = logging.getLogger("lifeops")
        for handler in list(logger.handlers):
            handler.flush()
            handler.close()
            logger.removeHandler(handler)
        _session_dir = None
        _session_id = None
        _started_at = None


def current_session_id() -> str:
    _ensure_session()
    assert _session_id is not None
    return _session_id


def current_session_files() -> dict[str, Path]:
    _ensure_session()
    assert _session_dir is not None
    return {
        "events": _session_dir / "events.jsonl",
        "llm": _session_dir / "llm.jsonl",
        "application": _session_dir / "application.log",
    }


def append_log_record(channel: str, event: str, fields: dict[str, Any]) -> None:
    """Append one durable JSONL record without rewriting prior events."""
    if channel not in {"events", "llm"}:
        raise ValueError(f"Unsupported structured log channel: {channel}")
    files = current_session_files()
    record = {
        "timestamp": now_iso(),
        "session_id": current_session_id(),
        "event": event,
        **json_safe(fields),
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with _lock, files[channel].open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()


def session_metadata() -> dict[str, str]:
    _ensure_session()
    assert _session_id is not None and _started_at is not None
    return {"session_id": _session_id, "started_at": _started_at}


def _ensure_session() -> None:
    if _session_dir is None:
        start_logging_session()


def _configure_application_handler(path: Path) -> None:
    logger = logging.getLogger("lifeops")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)
