"""Deterministic local text matching shared by Memory reads and conflicts."""

from __future__ import annotations

import re
import unicodedata


_TERM = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_memory_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("text must be a string.")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def memory_terms(text: str) -> tuple[str, ...]:
    normalized = normalize_memory_text(text)
    return tuple(dict.fromkeys(_TERM.findall(normalized)))


def memory_match_score(
    query: str,
    content: str,
    tags: tuple[str, ...],
) -> tuple[int, int, int]:
    normalized_query = normalize_memory_text(query)
    normalized_content = normalize_memory_text(content)
    normalized_tags = tuple(normalize_memory_text(tag) for tag in tags)
    terms = memory_terms(query)
    tag_exact = int(
        normalized_query in normalized_tags
        or any(term in normalized_tags for term in terms)
    )
    substring = int(bool(normalized_query) and normalized_query in normalized_content)
    searchable = " ".join((normalized_content, *normalized_tags))
    overlap = sum(1 for term in terms if term in searchable)
    return tag_exact, substring, overlap
