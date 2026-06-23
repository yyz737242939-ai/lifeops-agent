from pathlib import Path
from typing import Any

from app.utils.json_file import read_json_file, write_json_file
from app.utils.time import now_iso, timestamp_id


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
REF_DIR = LOG_DIR / "context_refs"


def save_context_ref(
    *,
    tool_name: str,
    full_result: Any,
    summary: Any,
) -> str:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    ref_id = f"ctx_{timestamp_id()}"
    ref_file = REF_DIR / f"{ref_id}.json"
    payload = {
        "ref_id": ref_id,
        "created_at": now_iso(),
        "tool_name": tool_name,
        "summary": summary,
        "full_result": full_result,
    }
    write_json_file(ref_file, payload)
    return ref_id


def read_context_ref(ref_id: str) -> dict[str, Any] | None:
    if not ref_id.startswith("ctx_"):
        return None

    ref_file = REF_DIR / f"{ref_id}.json"
    if not ref_file.exists():
        return None

    return read_json_file(ref_file, dict)
