"""Serialization helpers shared by storage and observability."""

from __future__ import annotations

import json
from typing import Any

from app.common.errors import SerializationError


def to_json(data: object) -> str:
    """Serialize data to deterministic JSON for SQLite payload columns."""
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SerializationError(
            "Failed to serialize data to JSON.",
            code="json_serialize_failed",
            details={"data_type": type(data).__name__},
        ) from exc


def from_json(raw: str) -> Any:
    """Parse a JSON payload from SQLite."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SerializationError(
            "Failed to parse JSON payload.",
            code="json_parse_failed",
            details={"position": exc.pos},
        ) from exc
