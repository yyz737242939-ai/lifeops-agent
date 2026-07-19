"""Verified deterministic active Memory retrieval for Context assembly."""

from __future__ import annotations

from app.context.models import (
    ContextContribution,
    ContextContributionKind,
    ContextProvenance,
    ContextQuery,
)
from app.memory.document_store import MemoryDocumentStore
from app.memory.errors import MemoryRepositoryError
from app.memory.repository import MemoryRepository
from app.memory.retrieval_core import select_verified_active_entries


class DeterministicMemoryRetriever:
    def __init__(
        self,
        repository: MemoryRepository,
        document_store: MemoryDocumentStore,
    ) -> None:
        self._repository = repository
        self._document_store = document_store

    def search(
        self,
        query: ContextQuery,
        max_items: int,
        max_tokens: int,
    ) -> tuple[ContextContribution, ...]:
        if not isinstance(query, ContextQuery):
            raise ValueError("query must be a ContextQuery.")
        _require_non_negative_int(max_items, "max_items")
        _require_non_negative_int(max_tokens, "max_tokens")
        if max_items == 0 or max_tokens == 0:
            return ()
        try:
            ranked = select_verified_active_entries(
                self._repository,
                self._document_store,
                query.text,
                max_items=max_items,
                max_tokens=max_tokens,
            )
        except MemoryRepositoryError:
            return ()
        selected: list[ContextContribution] = []
        for item in ranked:
            record = item.entry.record
            selected.append(
                ContextContribution(
                    kind=ContextContributionKind.MEMORY,
                    source="explicit_memory",
                    content=item.entry.document.content,
                    estimated_tokens=item.estimated_tokens,
                    provenance=ContextProvenance(
                        reference=f"memory://{record.memory_id}/v{record.version}",
                        attributes=(
                            ("memory_id", record.memory_id),
                            ("version", str(record.version)),
                            ("content_hash", record.content_hash),
                        ),
                    ),
                )
            )
        return tuple(selected)


def _require_non_negative_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")
