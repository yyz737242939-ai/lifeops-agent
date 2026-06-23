import json
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
IDEMPOTENCY_FILE = DATA_DIR / "idempotency.json"


def _load() -> dict[str, dict[str, Any]]:
    if not IDEMPOTENCY_FILE.exists():
        return {}
    try:
        payload = json.loads(IDEMPOTENCY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {IDEMPOTENCY_FILE}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{IDEMPOTENCY_FILE} must contain a JSON object")
    return payload


def get_result(key: str) -> dict[str, Any] | None:
    result = _load().get(key)
    return dict(result) if isinstance(result, dict) else None


def save_result(key: str, result: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entries = _load()
    entries[key] = result
    IDEMPOTENCY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
