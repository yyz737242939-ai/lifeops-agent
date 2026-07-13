"""Read-only Travel contracts for Planner, Context, and Memory consumers."""

from __future__ import annotations

from app.common.validation import require_non_empty_string
from app.domains.contracts import (
    DomainContextProvider,
    DomainMemoryCandidateProvider,
    DomainPlanningReadModel,
)
from app.domains.travel.models import (
    TravelContextCandidate,
    TravelPlanningSnapshot,
    TravelPreferenceCandidate,
)
from app.domains.travel.repository import TravelRepository


_REQUIRED_PLANNING_CONSTRAINTS = ("budget", "date", "destination", "traveler_count")
_PREFERENCE_KINDS = frozenset({"lodging", "other", "transport"})


class TravelReadService(
    DomainPlanningReadModel[TravelPlanningSnapshot],
    DomainContextProvider[TravelContextCandidate],
    DomainMemoryCandidateProvider[TravelPreferenceCandidate],
):
    def __init__(self, repository: TravelRepository) -> None:
        self._repository = repository

    def get_planning_snapshot(self, scope_id: str) -> TravelPlanningSnapshot:
        require_non_empty_string(scope_id, "scope_id")
        trip = self._repository.get_trip(scope_id)
        constraints = self._repository.list_constraints(scope_id)
        itineraries = self._repository.list_itineraries(scope_id)
        kinds = tuple(sorted({item.kind for item in constraints}))
        return TravelPlanningSnapshot(
            trip_id=trip.trip_id,
            title=trip.title,
            status=trip.status,
            trip_version=trip.version,
            constraint_kinds=kinds,
            missing_constraint_kinds=tuple(
                item for item in _REQUIRED_PLANNING_CONSTRAINTS if item not in kinds
            ),
            candidate_coverage=("saved_itinerary",) if itineraries else (),
            saved_itinerary_count=len(itineraries),
            latest_itinerary_version=(
                max(item.version for item in itineraries) if itineraries else None
            ),
            pending_decision_kinds=() if itineraries else ("itinerary",),
            updated_at=trip.updated_at,
        )

    def query_context_candidates(
        self,
        query: str,
        budget_hint: int,
        *,
        scope_id: str | None = None,
    ) -> tuple[TravelContextCandidate, ...]:
        require_non_empty_string(query, "query")
        trip_id = self._require_scope(scope_id)
        if not isinstance(budget_hint, int) or isinstance(budget_hint, bool) or budget_hint < 1:
            raise ValueError("budget_hint must be a positive integer.")
        trip = self._repository.get_trip(trip_id)
        constraints = self._repository.list_constraints(trip_id)
        itineraries = self._repository.list_itineraries(trip_id)
        raw = [
            TravelContextCandidate(
                f"travel-context-trip:{trip.trip_id}",
                "trip",
                f"{trip.title} ({trip.status})",
                f"travel-trip:{trip.trip_id}",
                len(trip.title) + len(trip.status) + 3,
                trip.updated_at,
            )
        ]
        raw.extend(
            TravelContextCandidate(
                f"travel-context-constraint:{item.constraint_id}",
                "constraint",
                f"{item.kind}: {item.value}",
                f"travel-constraint:{item.constraint_id}",
                len(item.kind) + len(item.value) + 2,
                item.updated_at,
            )
            for item in constraints
        )
        raw.extend(
            TravelContextCandidate(
                f"travel-context-itinerary:{item.itinerary_id}",
                "itinerary",
                item.summary,
                f"travel-itinerary:{item.itinerary_id}",
                len(item.summary),
                item.created_at,
            )
            for item in itineraries
        )
        normalized = query.casefold()
        matching = tuple(item for item in raw if normalized in item.content.casefold())
        selected: list[TravelContextCandidate] = []
        used = 0
        for item in matching:
            if used + item.estimated_chars <= budget_hint:
                selected.append(item)
                used += item.estimated_chars
        return tuple(selected)

    def query_memory_candidates(
        self,
        query: str,
        limit: int,
        *,
        scope_id: str | None = None,
    ) -> tuple[TravelPreferenceCandidate, ...]:
        require_non_empty_string(query, "query")
        trip_id = self._require_scope(scope_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50.")
        normalized = query.casefold()
        candidates = tuple(
            TravelPreferenceCandidate(
                f"travel-preference:{item.constraint_id}",
                item.kind,
                item.value,
                f"travel-constraint:{item.constraint_id}",
                item.updated_at,
            )
            for item in self._repository.list_constraints(trip_id)
            if item.kind in _PREFERENCE_KINDS
            and normalized in f"{item.kind} {item.value}".casefold()
        )
        return candidates[:limit]

    @staticmethod
    def _require_scope(scope_id: str | None) -> str:
        if scope_id is None:
            raise ValueError("Travel queries require Trip scope_id.")
        require_non_empty_string(scope_id, "scope_id")
        return scope_id
