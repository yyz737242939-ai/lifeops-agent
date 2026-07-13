"""Read-only contracts for future Planner, Context, and Memory consumers."""

from __future__ import annotations

from app.common.validation import require_non_empty_string
from app.domains.contracts import (
    DomainContextProvider,
    DomainMemoryCandidateProvider,
    DomainPlanningReadModel,
)
from app.domains.research.models import (
    ResearchContextCandidate,
    ResearchMemoryCandidate,
    ResearchPlanningSnapshot,
    ResearchSavedItem,
)
from app.domains.research.repository import ResearchRepository


class ResearchReadService(
    DomainPlanningReadModel[ResearchPlanningSnapshot],
    DomainContextProvider[ResearchContextCandidate],
    DomainMemoryCandidateProvider[ResearchMemoryCandidate],
):
    """SQLite-backed facade implementing all three read-only contracts."""

    def __init__(self, repository: ResearchRepository) -> None:
        self._repository = repository

    def get_planning_snapshot(self, scope_id: str) -> ResearchPlanningSnapshot:
        require_non_empty_string(scope_id, "scope_id")
        return self._repository.get_planning_snapshot(scope_id)

    def query_context_candidates(
        self,
        query: str,
        budget_hint: int,
        *,
        scope_id: str | None = None,
    ) -> tuple[ResearchContextCandidate, ...]:
        require_non_empty_string(query, "query")
        if scope_id is not None:
            require_non_empty_string(scope_id, "scope_id")
            raise ValueError("Research context scope_id is not supported yet.")
        if not isinstance(budget_hint, int) or isinstance(budget_hint, bool) or budget_hint < 1:
            raise ValueError("budget_hint must be a positive integer.")
        return self._repository.query_context_candidates(query, budget_hint)

    def query_memory_candidates(
        self,
        query: str,
        limit: int,
        *,
        scope_id: str | None = None,
    ) -> tuple[ResearchMemoryCandidate, ...]:
        require_non_empty_string(query, "query")
        if scope_id is not None:
            require_non_empty_string(scope_id, "scope_id")
            raise ValueError("Research memory scope_id is not supported yet.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50.")
        return self._repository.query_memory_candidates(query, limit)

    def search_saved_items(
        self,
        query: str,
        item_kinds: tuple[str, ...],
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[ResearchSavedItem, ...]:
        require_non_empty_string(query, "query")
        if not isinstance(item_kinds, tuple) or not item_kinds:
            raise ValueError("item_kinds must be a non-empty tuple.")
        if len(set(item_kinds)) != len(item_kinds) or any(
            item_kind not in {"source", "note", "brief"}
            for item_kind in item_kinds
        ):
            raise ValueError("item_kinds contains unsupported or duplicate values.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be a non-negative integer.")
        return self._repository.search_saved_items(query, item_kinds, limit, offset)
