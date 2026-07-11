"""Shared text normalization and simple matching helpers."""

from __future__ import annotations


def normalize_search_text(text: str) -> str:
    """Normalize case and whitespace for deterministic keyword matching."""

    return " ".join(text.strip().lower().split())


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Return whether any literal pattern occurs in the supplied text."""

    return any(pattern in text for pattern in patterns)
