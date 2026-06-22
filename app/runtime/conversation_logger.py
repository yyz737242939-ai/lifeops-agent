import json
from datetime import datetime
from pathlib import Path
from typing import Any


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
CONVERSATION_DIR = LOG_DIR / "conversations"

_trace_file: Path | None = None
_raw_file: Path | None = None
_trace_data: dict[str, Any] | None = None
_raw_data: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def start_logging_session() -> dict[str, Path]:
    global _raw_data, _raw_file, _trace_data, _trace_file

    CONVERSATION_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    session_id = f"session_{timestamp}"

    _trace_file = CONVERSATION_DIR / f"{session_id}_trace.json"
    _raw_file = CONVERSATION_DIR / f"{session_id}_raw.json"
    _trace_data = {
        "session_id": session_id,
        "started_at": _now_iso(),
        "kind": "structured_trace",
        "events": [],
    }
    _raw_data = {
        "session_id": session_id,
        "started_at": _now_iso(),
        "kind": "raw_llm_io",
        "events": [],
    }
    _write_trace()
    _write_raw()
    return {"trace": _trace_file, "raw": _raw_file}


def current_session_files() -> dict[str, Path]:
    if _trace_file is None or _raw_file is None:
        return start_logging_session()
    return {"trace": _trace_file, "raw": _raw_file}


def log_event(event: str, **fields: Any) -> None:
    if _trace_data is None:
        start_logging_session()

    assert _trace_data is not None
    _trace_data["events"].append(
        {
            "timestamp": _now_iso(),
            "event": event,
            **_json_safe(fields),
        }
    )
    _write_trace()


def log_raw_event(event: str, **fields: Any) -> None:
    if _raw_data is None:
        start_logging_session()

    assert _raw_data is not None
    _raw_data["events"].append(
        {
            "timestamp": _now_iso(),
            "event": event,
            **_json_safe(fields),
        }
    )
    _write_raw()


def _write_trace() -> None:
    assert _trace_file is not None
    assert _trace_data is not None
    _trace_file.write_text(
        json.dumps(_trace_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_raw() -> None:
    assert _raw_file is not None
    assert _raw_data is not None
    _raw_file.write_text(
        json.dumps(_raw_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
