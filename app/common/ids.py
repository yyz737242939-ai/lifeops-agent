"""ID helpers for runtime records."""

from __future__ import annotations

from uuid import uuid4


def new_id(prefix: str) -> str:
    """Return a stable text ID with a readable prefix."""
    if not prefix or not prefix.strip():
        raise ValueError("ID prefix must be a non-empty string.")

    normalized = prefix.strip().replace("_", "-")
    return f"{normalized}_{uuid4().hex}"
