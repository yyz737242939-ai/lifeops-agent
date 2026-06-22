import json
from datetime import datetime
from pathlib import Path
from typing import Any


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
REF_DIR = LOG_DIR / "context_refs"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _timestamp_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def save_context_ref(
    *,
    tool_name: str,
    full_result: Any,
    summary: Any,
) -> str:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    ref_id = f"ctx_{_timestamp_id()}"
    ref_file = REF_DIR / f"{ref_id}.json"
    payload = {
        "ref_id": ref_id,
        "created_at": _now_iso(),
        "tool_name": tool_name,
        "summary": summary,
        "full_result": full_result,
    }
    ref_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ref_id


def read_context_ref(ref_id: str) -> dict[str, Any] | None:
    if not ref_id.startswith("ctx_"):
        return None

    ref_file = REF_DIR / f"{ref_id}.json"
    if not ref_file.exists():
        return None

    try:
        payload = json.loads(ref_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {ref_file}") from e

    if not isinstance(payload, dict):
        raise ValueError(f"{ref_file} must contain a JSON object")
    return payload
