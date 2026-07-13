"""Request-local Travel option workflow service."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from collections.abc import Callable

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.references import (
    KnowledgeReference,
    KnowledgeReferenceResolution,
    KnowledgeReferenceResolutionError,
    KnowledgeReferenceResolver,
)
from app.domains.travel.models import (
    CalendarAvailabilityCandidate,
    CandidateAssessment,
    ExternalLookupResult,
    Itinerary,
    ItineraryDraft,
    ItineraryItem,
    ItinerarySaveResult,
    LodgingCandidate,
    PlaceCandidate,
    TransportCandidate,
    TravelComparison,
    TravelConstraint,
    TravelDecision,
    TravelKnowledgeReference,
    TravelKnowledgeView,
    Trip,
    WeatherInformationCandidate,
)
from app.domains.travel.ports import (
    CalendarAvailabilityPort,
    CalendarAvailabilityQuery,
    LodgingSearchPort,
    LodgingSearchQuery,
    PlaceSearchPort,
    PlaceSearchQuery,
    TransportSearchPort,
    TransportSearchQuery,
    WeatherInformationPort,
    WeatherInformationQuery,
)
from app.domains.travel.repository import TravelRepository


class TravelService:
    def __init__(
        self,
        repository: TravelRepository,
        *,
        calendar_port: CalendarAvailabilityPort | None = None,
        weather_port: WeatherInformationPort | None = None,
        transport_port: TransportSearchPort | None = None,
        lodging_port: LodgingSearchPort | None = None,
        place_port: PlaceSearchPort | None = None,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._repository = repository
        self._calendar_port = calendar_port
        self._weather_port = weather_port
        self._transport_port = transport_port
        self._lodging_port = lodging_port
        self._place_port = place_port
        self._clock = clock
        self._external_results: dict[str, ExternalLookupResult] = {}
        self._comparisons: dict[str, TravelComparison] = {}
        self._drafts: dict[str, ItineraryDraft] = {}

    def check_calendar_availability(
        self, query: CalendarAvailabilityQuery
    ) -> ExternalLookupResult[CalendarAvailabilityCandidate]:
        port = self._require_port(self._calendar_port, "calendar")
        return self._remember_result(port.check_availability(query))

    def get_weather(
        self, query: WeatherInformationQuery
    ) -> ExternalLookupResult[WeatherInformationCandidate]:
        port = self._require_port(self._weather_port, "weather")
        return self._remember_result(port.get_weather(query))

    def search_transport(
        self, query: TransportSearchQuery
    ) -> ExternalLookupResult[TransportCandidate]:
        port = self._require_port(self._transport_port, "transport")
        return self._remember_result(port.search_transport(query))

    def search_lodging(
        self, query: LodgingSearchQuery
    ) -> ExternalLookupResult[LodgingCandidate]:
        port = self._require_port(self._lodging_port, "lodging")
        return self._remember_result(port.search_lodging(query))

    def search_places(
        self, query: PlaceSearchQuery
    ) -> ExternalLookupResult[PlaceCandidate]:
        port = self._require_port(self._place_port, "place")
        return self._remember_result(port.search_places(query))

    def compare_candidates(
        self, trip_id: str, observation_ids: tuple[str, ...]
    ) -> TravelComparison:
        trip = self.get_trip(trip_id)
        if trip.status != "active":
            raise ValueError("Archived trips cannot create comparisons.")
        if not observation_ids or len(set(observation_ids)) != len(observation_ids):
            raise ValueError("observation_ids must be non-empty and unique.")
        try:
            results = tuple(self._external_results[item] for item in observation_ids)
        except KeyError as exc:
            raise ValueError(
                "observation_id is not available in this request."
            ) from exc
        constraints = self.get_trip_constraints(trip_id)
        assessments = tuple(
            self._assess_candidate(candidate, result, constraints)
            for result in results
            for candidate in result.candidates
        )
        if not assessments:
            raise ValueError("No request-local candidates are available to compare.")
        comparison = TravelComparison(
            comparison_id=new_id("travel-comparison"),
            trip_id=trip_id,
            observation_ids=observation_ids,
            assessments=assessments,
            empty_observation_ids=tuple(
                result.observation.observation_id
                for result in results
                if not result.candidates
            ),
            failures=tuple(
                failure for result in results for failure in result.failures
            ),
            created_at=utc_now_iso(),
        )
        self._comparisons[comparison.comparison_id] = comparison
        return comparison

    def build_itinerary_draft(
        self,
        comparison_id: str,
        candidate_ids: tuple[str, ...],
        summary: str,
    ) -> ItineraryDraft:
        try:
            comparison = self._comparisons[comparison_id]
        except KeyError as exc:
            raise ValueError(
                "comparison_id is not available in this request."
            ) from exc
        trip = self.get_trip(comparison.trip_id)
        if trip.status != "active":
            raise ValueError("Archived trips cannot create itinerary drafts.")
        if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate_ids must be non-empty and unique.")
        by_id = {item.candidate_id: item for item in comparison.assessments}
        try:
            selected = tuple(by_id[item] for item in candidate_ids)
        except KeyError as exc:
            raise ValueError(
                "candidate_id is not available in this comparison."
            ) from exc
        if any(item.expired for item in selected):
            raise ValueError("Expired candidates cannot enter an itinerary draft.")
        if any(item.conflicting_constraint_ids for item in selected):
            raise ValueError("Conflicting candidates cannot enter an itinerary draft.")
        candidate_observations = {
            candidate.candidate_id: observation_id
            for observation_id in comparison.observation_ids
            for candidate in self._external_results[observation_id].candidates
        }
        selected_observation_ids = tuple(
            dict.fromkeys(candidate_observations[item] for item in candidate_ids)
        )
        version = (
            max(
                (
                    item.version
                    for item in self._drafts.values()
                    if item.trip_id == comparison.trip_id
                ),
                default=0,
            )
            + 1
        )
        draft = ItineraryDraft(
            draft_id=new_id("itinerary-draft"),
            trip_id=comparison.trip_id,
            candidate_ids=candidate_ids,
            summary=summary,
            version=version,
            created_at=utc_now_iso(),
            comparison_id=comparison_id,
            observation_ids=selected_observation_ids,
        )
        self._drafts[draft.draft_id] = draft
        return draft

    def create_trip(self, title: str) -> Trip:
        return self._repository.create_trip(title)

    def get_trip(self, trip_id: str) -> Trip:
        return self._repository.get_trip(trip_id)

    def list_trips(self, *, include_archived: bool = False) -> tuple[Trip, ...]:
        return self._repository.list_trips(include_archived=include_archived)

    def update_trip_constraints(
        self,
        trip_id: str,
        constraints: tuple[tuple[str, str], ...],
        *,
        expected_version: int,
    ) -> tuple[TravelConstraint, ...]:
        return self._repository.replace_constraints(
            trip_id, constraints, expected_version=expected_version
        )

    def get_trip_constraints(self, trip_id: str) -> tuple[TravelConstraint, ...]:
        return self._repository.list_constraints(trip_id)

    def archive_trip(self, trip_id: str, *, expected_version: int) -> Trip:
        return self._repository.archive_trip(trip_id, expected_version=expected_version)

    def add_knowledge_reference(
        self, trip_id: str, domain: str, item_kind: str, item_id: str
    ) -> TravelKnowledgeReference:
        reference = KnowledgeReference(
            new_id("knowledge-reference"), domain, item_kind, item_id
        )
        return self._repository.add_knowledge_reference(trip_id, reference)

    def get_trip_with_knowledge(
        self, trip_id: str, resolver: KnowledgeReferenceResolver
    ) -> TravelKnowledgeView:
        trip = self.get_trip(trip_id)
        resolutions: list[KnowledgeReferenceResolution] = []
        for saved in self._repository.list_knowledge_references(trip_id):
            try:
                resolution = resolver.resolve(saved.reference)
            except KnowledgeReferenceResolutionError as exc:
                resolution = KnowledgeReferenceResolution(
                    saved.reference,
                    "unavailable",
                    error_code=exc.code,
                )
            if resolution.reference != saved.reference:
                raise ValueError("resolver returned a different KnowledgeReference.")
            resolutions.append(resolution)
        return TravelKnowledgeView(trip, tuple(resolutions))

    def save_itinerary(
        self, draft_id: str, idempotency_key: str
    ) -> ItinerarySaveResult:
        try:
            draft = self._drafts[draft_id]
        except KeyError as exc:
            raise ValueError("draft_id is not available in this request.") from exc
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string.")
        existing = self._repository.get_idempotent_itinerary_save(
            idempotency_key, draft.draft_id
        )
        if existing is not None:
            return existing
        comparison = self._comparisons[draft.comparison_id]
        candidates = {
            candidate.candidate_id: candidate
            for observation_id in comparison.observation_ids
            for candidate in self._external_results[observation_id].candidates
        }
        selected = tuple(candidates[item] for item in draft.candidate_ids)
        observations = tuple(
            self._external_results[item].observation
            for item in draft.observation_ids
        )
        if any(self._is_expired(item.expires_at) for item in observations):
            raise ValueError("Expired candidates cannot be saved as an itinerary.")
        expires_at_values = tuple(
            item.expires_at for item in observations if item.expires_at is not None
        )
        if not expires_at_values:
            raise ValueError("Selected candidates do not have saveable expiry metadata.")
        now = self._clock()
        destination = next(
            (
                item.value
                for item in self.get_trip_constraints(draft.trip_id)
                if item.kind == "destination"
            ),
            str(
                next(
                    (
                        getattr(item, "destination", getattr(item, "location", ""))
                        for item in selected
                        if getattr(
                            item, "destination", getattr(item, "location", "")
                        )
                    ),
                    "Unspecified destination",
                )
            ),
        )
        itinerary = Itinerary(
            itinerary_id=new_id("itinerary"),
            destination=destination,
            transport=self._selected_summary(selected, "transport"),
            lodging=self._selected_summary(selected, "lodging"),
            summary=draft.summary,
            observed_at=max(item.observed_at for item in observations),
            expires_at=min(expires_at_values),
            provenance=f"travel-draft:{draft.draft_id}",
            created_at=now,
            trip_id=draft.trip_id,
            draft_id=draft.draft_id,
            idempotency_key=idempotency_key,
            version=draft.version,
        )
        items = tuple(
            self._itinerary_item(itinerary.itinerary_id, item, position, now)
            for position, item in enumerate(selected, start=1)
        )
        decision = TravelDecision(
            decision_id=new_id("travel-decision"),
            trip_id=draft.trip_id,
            kind="itinerary",
            selected_candidate_ids=draft.candidate_ids,
            rationale=draft.summary,
            decided_at=now,
            itinerary_id=itinerary.itinerary_id,
        )
        return self._repository.save_itinerary_bundle(itinerary, items, decision)

    def _remember_result(self, result: ExternalLookupResult) -> ExternalLookupResult:
        self._external_results[result.observation.observation_id] = result
        return result

    @staticmethod
    def _require_port(port, capability: str):
        if port is None:
            raise ValueError(f"{capability} port is not configured.")
        return port

    def _assess_candidate(self, candidate, result, constraints) -> CandidateAssessment:
        matched: list[str] = []
        conflicts: list[str] = []
        unresolved: list[str] = []
        for constraint in constraints:
            outcome = TravelService._constraint_outcome(
                candidate, constraint.kind, constraint.value
            )
            if outcome == "matched":
                matched.append(constraint.constraint_id)
            elif outcome == "conflict":
                conflicts.append(constraint.constraint_id)
            else:
                unresolved.append(constraint.constraint_id)
        expired = self._is_expired(result.observation.expires_at)
        return CandidateAssessment(
            candidate_id=candidate.candidate_id,
            candidate_kind=TravelService._candidate_kind(candidate),
            matched_constraint_ids=tuple(matched),
            conflicting_constraint_ids=tuple(conflicts),
            unresolved_constraint_ids=tuple(unresolved),
            expired=expired,
            summary=TravelService._candidate_summary(candidate),
        )

    def _is_expired(self, expires_at: str | None) -> bool:
        if expires_at is None:
            return False
        now = datetime.fromisoformat(self._clock())
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return datetime.fromisoformat(expires_at) <= now

    @staticmethod
    def _constraint_outcome(candidate, kind: str, value: str) -> str:
        if kind == "destination":
            actual = getattr(
                candidate, "destination", getattr(candidate, "location", None)
            )
            if actual is None:
                return "unresolved"
            return "matched" if str(actual).casefold() == value.casefold() else "conflict"
        if kind == "budget":
            price_minor = getattr(candidate, "price_minor", None)
            currency = getattr(candidate, "currency", None)
            parts = value.split()
            if price_minor is None or currency is None or len(parts) != 2:
                return "unresolved"
            try:
                budget_minor = int(Decimal(parts[1]) * 100)
            except (InvalidOperation, ValueError):
                return "unresolved"
            if str(currency).casefold() != parts[0].casefold():
                return "conflict"
            return "matched" if int(price_minor) <= budget_minor else "conflict"
        return "unresolved"

    @staticmethod
    def _candidate_kind(candidate) -> str:
        if isinstance(candidate, CalendarAvailabilityCandidate):
            return "calendar"
        if isinstance(candidate, WeatherInformationCandidate):
            return "weather"
        if isinstance(candidate, TransportCandidate):
            return "transport"
        if isinstance(candidate, LodgingCandidate):
            return "lodging"
        if isinstance(candidate, PlaceCandidate):
            return "place"
        raise ValueError("Unsupported Travel candidate type.")

    @staticmethod
    def _candidate_summary(candidate) -> str:
        label = getattr(candidate, "name", None)
        if label is None:
            label = getattr(candidate, "destination", None)
        if label is None:
            label = getattr(candidate, "location", None)
        return (
            f"{TravelService._candidate_kind(candidate)} candidate: "
            f"{label or candidate.candidate_id}"
        )

    @staticmethod
    def _selected_summary(candidates: tuple, kind: str) -> str:
        selected = tuple(
            TravelService._candidate_summary(item)
            for item in candidates
            if TravelService._candidate_kind(item) == kind
        )
        return "; ".join(selected) if selected else f"No {kind} candidate selected."

    @staticmethod
    def _itinerary_item(
        itinerary_id: str, candidate, position: int, created_at: str
    ) -> ItineraryItem:
        kind = TravelService._candidate_kind(candidate)
        starts_at: str | None = None
        ends_at: str | None = None
        if isinstance(candidate, CalendarAvailabilityCandidate):
            starts_at, ends_at = candidate.starts_at, candidate.ends_at
        elif isinstance(candidate, TransportCandidate):
            starts_at, ends_at = candidate.departs_at, candidate.arrives_at
        elif isinstance(candidate, LodgingCandidate):
            starts_at, ends_at = candidate.check_in, candidate.check_out
        elif isinstance(candidate, WeatherInformationCandidate):
            starts_at = f"{candidate.date}T00:00:00"
            ends_at = f"{candidate.date}T23:59:59"
        return ItineraryItem(
            item_id=new_id("itinerary-item"),
            itinerary_id=itinerary_id,
            day_number=position,
            title=TravelService._candidate_summary(candidate),
            item_type=kind,
            starts_at=starts_at,
            ends_at=ends_at,
            created_at=created_at,
            source_candidate_id=candidate.candidate_id,
            notes="Planning fact only; no booking was made.",
        )
