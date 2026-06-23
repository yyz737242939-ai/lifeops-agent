from pathlib import Path
from typing import Any

from app.utils.json_file import read_json_file, write_json_file


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
IDEMPOTENCY_FILE = DATA_DIR / "idempotency.json"


def _load() -> dict[str, dict[str, Any]]:
    if not IDEMPOTENCY_FILE.exists():
        return {}
    return read_json_file(IDEMPOTENCY_FILE, dict)


def get_result(key: str) -> dict[str, Any] | None:
    """Return a defensive copy of one cached write result."""
    result = _load().get(key)
    return dict(result) if isinstance(result, dict) else None


def save_result(key: str, result: dict[str, Any]) -> None:
    """Persist a successful result under its idempotency key."""
    entries = _load()
    entries[key] = result
    write_json_file(IDEMPOTENCY_FILE, entries)
