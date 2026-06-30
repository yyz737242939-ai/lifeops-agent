from pathlib import Path
from typing import Any
from datetime import datetime, timedelta
import hashlib
import json

from app.utils.json_file import read_json_file, write_json_file
from app.utils.time import now_iso, timestamp_id


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
REF_DIR = LOG_DIR / "context_refs"
DEFAULT_TTL_DAYS = 7


def save_context_ref(
    *,
    tool_name: str,
    full_result: Any,
    summary: Any,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> str:
    """Persist a complete tool result and return its compact reference id."""
    REF_DIR.mkdir(parents=True, exist_ok=True)
    ref_id = f"ctx_{timestamp_id()}"
    ref_file = REF_DIR / f"{ref_id}.json"
    created_at = now_iso()
    expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat(
        timespec="seconds"
    )
    payload = {
        "ref_id": ref_id,
        "created_at": created_at,
        "expires_at": expires_at,
        "tool_name": tool_name,
        "summary": summary,
        "full_result": full_result,
        "payload_hash": _payload_hash(full_result),
    }
    write_json_file(ref_file, payload)
    return ref_id


def read_context_ref(ref_id: str) -> dict[str, Any] | None:
    """Read a validated Context Ref without accepting arbitrary paths."""
    if not ref_id.startswith("ctx_"):
        return None

    ref_file = REF_DIR / f"{ref_id}.json"
    if not ref_file.exists():
        return None

    payload = read_json_file(ref_file, dict)
    if _is_expired(payload.get("expires_at")):
        return None
    return payload


def _payload_hash(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _is_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, str):
        return False
    try:
        return datetime.fromisoformat(expires_at) <= datetime.now()
    except ValueError:
        return True
