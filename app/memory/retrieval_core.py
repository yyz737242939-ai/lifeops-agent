"""Shared verified ranking used by MemoryService and the Context adapter."""

from __future__ import annotations

from dataclasses import dataclass

from app.context.budget import estimate_tokens
from app.memory.document_store import MemoryDocumentStore
from app.memory.errors import MemoryDocumentStoreError
from app.memory.matching import memory_match_score
from app.memory.models import MemoryEntry, MemoryIndexRecord, decode_memory_tags
from app.memory.repository import MemoryRepository


@dataclass(frozen=True)
class RankedMemoryEntry:
    entry: MemoryEntry
    estimated_tokens: int
    score: tuple[int, int, int]


def select_verified_active_entries(
    repository: MemoryRepository,
    document_store: MemoryDocumentStore,
    query: str,
    *,
    max_items: int,
    max_tokens: int | None,
) -> tuple[RankedMemoryEntry, ...]:
    _require_non_negative_int(max_items, "max_items")
    if max_tokens is not None:
        _require_non_negative_int(max_tokens, "max_tokens")
    if max_items == 0 or max_tokens == 0:
        return ()

    ranked: list[RankedMemoryEntry] = []
    for record in repository.list_active_index():
        candidate = _rank_one(document_store, record, query)
        if candidate is not None:
            ranked.append(candidate)
    ranked.sort(key=lambda item: item.entry.record.memory_id)
    ranked.sort(key=lambda item: item.entry.record.updated_at, reverse=True)
    ranked.sort(key=lambda item: item.score[2], reverse=True)
    ranked.sort(key=lambda item: item.score[1], reverse=True)
    ranked.sort(key=lambda item: item.score[0], reverse=True)

    selected: list[RankedMemoryEntry] = []
    used_tokens = 0
    for item in ranked:
        if len(selected) >= max_items:
            break
        if max_tokens is not None and used_tokens + item.estimated_tokens > max_tokens:
            continue
        selected.append(item)
        used_tokens += item.estimated_tokens
    return tuple(selected)


def _rank_one(
    document_store: MemoryDocumentStore,
    record: MemoryIndexRecord,
    query: str,
) -> RankedMemoryEntry | None:
    try:
        document = document_store.read_verified(record.relative_path, record.content_hash)
    except MemoryDocumentStoreError:
        return None
    score = memory_match_score(query, document.content, decode_memory_tags(record.tags_json))
    if score == (0, 0, 0):
        return None
    return RankedMemoryEntry(
        MemoryEntry(document, record),
        estimate_tokens(document.content),
        score,
    )


def _require_non_negative_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")
