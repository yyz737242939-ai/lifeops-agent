"""Shared read-only contracts implemented by LifeOps business domains."""

from __future__ import annotations

from typing import Protocol, TypeVar


PlanningSnapshotT_co = TypeVar("PlanningSnapshotT_co", covariant=True)
ContextCandidateT_co = TypeVar("ContextCandidateT_co", covariant=True)
MemoryCandidateT_co = TypeVar("MemoryCandidateT_co", covariant=True)


class DomainPlanningReadModel(Protocol[PlanningSnapshotT_co]):
    """Return one compact planning snapshot for a domain scope."""

    def get_planning_snapshot(self, scope_id: str) -> PlanningSnapshotT_co:
        ...


class DomainContextProvider(Protocol[ContextCandidateT_co]):
    """Return budget-aware context candidates without assembling a prompt."""

    def query_context_candidates(
        self,
        query: str,
        budget_hint: int,
        *,
        scope_id: str | None = None,
    ) -> tuple[ContextCandidateT_co, ...]:
        ...


class DomainMemoryCandidateProvider(Protocol[MemoryCandidateT_co]):
    """Return candidates for later Memory evaluation without writing Memory."""

    def query_memory_candidates(
        self,
        query: str,
        limit: int,
        *,
        scope_id: str | None = None,
    ) -> tuple[MemoryCandidateT_co, ...]:
        ...
