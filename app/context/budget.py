"""Deterministic local token estimates for Context budgeting."""

from __future__ import annotations


ESTIMATED_CHARACTERS_PER_TOKEN = 4


def normalize_text_for_token_estimate(text: str) -> str:
    """Collapse surrounding and repeated whitespace without provider tokenizers."""

    if not isinstance(text, str):
        raise ValueError("text must be a string.")
    return " ".join(text.split())


def estimate_tokens(text: str) -> int:
    """Return a stable ceil(normalized characters / fixed constant) estimate."""

    normalized = normalize_text_for_token_estimate(text)
    if not normalized:
        return 0
    return (
        len(normalized) + ESTIMATED_CHARACTERS_PER_TOKEN - 1
    ) // ESTIMATED_CHARACTERS_PER_TOKEN
