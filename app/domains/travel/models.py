"""Travel domain facts and request-local planning models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from app.common.validation import (
    require_non_empty_string,
    require_unique_non_empty_strings,
)
from app.domains.references import KnowledgeReference, KnowledgeReferenceResolution


TRIP_STATUSES = frozenset({"active", "archived"})
TRAVEL_CONSTRAINT_KINDS = frozenset(
    {
        "budget",
        "date",
        "destination",
        "document",
        "lodging",
        "other",
        "transport",
        "traveler_count",
    }
)
TRAVEL_DECISION_KINDS = frozenset(
    {"calendar", "destination", "itinerary", "lodging", "place", "transport"}
)
EXTERNAL_LOOKUP_STATUSES = frozenset(
    {"success", "no_results", "partial_failure", "failed"}
)
PROVIDER_FAILURE_CODES = frozenset(
    {"expired", "no_results", "provider_error", "rate_limit", "timeout"}
)


def _require_positive_integer(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


def _require_supported_value(
    value: str, field_name: str, supported_values: frozenset[str]
) -> None:
    require_non_empty_string(value, field_name)
    if value not in supported_values:
        raise ValueError(
            f"{field_name} must be one of: {', '.join(sorted(supported_values))}."
        )


def _parse_datetime(value: str, field_name: str) -> datetime:
    require_non_empty_string(value, field_name)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 datetime.") from exc


@dataclass(frozen=True)
class Trip:
    trip_id: str
    title: str
    status: str
    version: int
    created_at: str
    updated_at: str
    archived_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("trip_id", "title", "created_at", "updated_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_supported_value(self.status, "status", TRIP_STATUSES)
        _require_positive_integer(self.version, "version")
        if self.status == "active" and self.archived_at is not None:
            raise ValueError("An active trip cannot have archived_at.")
        if self.status == "archived":
            require_non_empty_string(self.archived_at, "archived_at")


@dataclass(frozen=True)
class TravelConstraint:
    constraint_id: str
    trip_id: str
    kind: str
    value: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "constraint_id",
            "trip_id",
            "value",
            "created_at",
            "updated_at",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_supported_value(self.kind, "kind", TRAVEL_CONSTRAINT_KINDS)


@dataclass(frozen=True)
class TravelKnowledgeReference:
    trip_id: str
    reference: KnowledgeReference
    created_at: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.trip_id, "trip_id")
        require_non_empty_string(self.created_at, "created_at")
        if not isinstance(self.reference, KnowledgeReference):
            raise ValueError("reference must be a KnowledgeReference.")


@dataclass(frozen=True)
class TravelKnowledgeView:
    trip: Trip
    references: tuple[KnowledgeReferenceResolution, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.trip, Trip):
            raise ValueError("trip must be a Trip.")
        if not isinstance(self.references, tuple) or any(
            not isinstance(item, KnowledgeReferenceResolution)
            for item in self.references
        ):
            raise ValueError(
                "references must contain KnowledgeReferenceResolution values."
            )


@dataclass(frozen=True)
class ExternalObservationRef:
    observation_id: str
    provider: str
    source_ref: str
    observed_at: str
    expires_at: str | None
    provenance: str

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "provider",
            "source_ref",
            "observed_at",
            "provenance",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        if self.expires_at is not None:
            require_non_empty_string(self.expires_at, "expires_at")


@dataclass(frozen=True)
class ProviderFailure:
    provider: str
    code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        for field_name in ("provider", "message"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_supported_value(self.code, "code", PROVIDER_FAILURE_CODES)
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a bool.")


@dataclass(frozen=True)
class CalendarAvailabilityCandidate:
    candidate_id: str
    observation_id: str
    starts_at: str
    ends_at: str
    timezone: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)
        if _parse_datetime(self.ends_at, "ends_at") <= _parse_datetime(
            self.starts_at, "starts_at"
        ):
            raise ValueError("ends_at must be later than starts_at.")


@dataclass(frozen=True)
class WeatherInformationCandidate:
    candidate_id: str
    observation_id: str
    location: str
    date: str
    condition: str
    temperature_min: float
    temperature_max: float
    temperature_unit: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "observation_id",
            "location",
            "date",
            "condition",
            "temperature_unit",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        for field_name in ("temperature_min", "temperature_max"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{field_name} must be a number.")
        if self.temperature_max < self.temperature_min:
            raise ValueError("temperature_max must not be below temperature_min.")


@dataclass(frozen=True)
class TransportCandidate:
    candidate_id: str
    observation_id: str
    origin: str
    destination: str
    mode: str
    departs_at: str
    arrives_at: str
    price_minor: int
    currency: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "observation_id",
            "origin",
            "destination",
            "mode",
            "departs_at",
            "arrives_at",
            "currency",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        if not isinstance(self.price_minor, int) or isinstance(self.price_minor, bool):
            raise ValueError("price_minor must be an integer.")
        if self.price_minor < 0:
            raise ValueError("price_minor must not be negative.")
        if _parse_datetime(self.arrives_at, "arrives_at") <= _parse_datetime(
            self.departs_at, "departs_at"
        ):
            raise ValueError("arrives_at must be later than departs_at.")


@dataclass(frozen=True)
class LodgingCandidate:
    candidate_id: str
    observation_id: str
    destination: str
    name: str
    check_in: str
    check_out: str
    price_minor: int
    currency: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "observation_id",
            "destination",
            "name",
            "check_in",
            "check_out",
            "currency",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        if not isinstance(self.price_minor, int) or isinstance(self.price_minor, bool):
            raise ValueError("price_minor must be an integer.")
        if self.price_minor < 0:
            raise ValueError("price_minor must not be negative.")
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be later than check_in.")


@dataclass(frozen=True)
class PlaceCandidate:
    candidate_id: str
    observation_id: str
    destination: str
    name: str
    category: str
    summary: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


ExternalCandidateT = TypeVar(
    "ExternalCandidateT",
    CalendarAvailabilityCandidate,
    WeatherInformationCandidate,
    TransportCandidate,
    LodgingCandidate,
    PlaceCandidate,
)
_EXTERNAL_CANDIDATE_TYPES = (
    CalendarAvailabilityCandidate,
    WeatherInformationCandidate,
    TransportCandidate,
    LodgingCandidate,
    PlaceCandidate,
)


@dataclass(frozen=True)
class ExternalLookupResult(Generic[ExternalCandidateT]):
    status: str
    observation: ExternalObservationRef
    candidates: tuple[ExternalCandidateT, ...]
    failures: tuple[ProviderFailure, ...] = ()

    def __post_init__(self) -> None:
        _require_supported_value(self.status, "status", EXTERNAL_LOOKUP_STATUSES)
        if not isinstance(self.observation, ExternalObservationRef):
            raise ValueError("observation must be an ExternalObservationRef.")
        if not isinstance(self.candidates, tuple):
            raise ValueError("candidates must be a tuple.")
        if any(
            not isinstance(item, _EXTERNAL_CANDIDATE_TYPES)
            for item in self.candidates
        ):
            raise ValueError("candidates must contain typed Travel candidates.")
        if not isinstance(self.failures, tuple) or any(
            not isinstance(item, ProviderFailure) for item in self.failures
        ):
            raise ValueError("failures must contain ProviderFailure values.")
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        require_unique_non_empty_strings(candidate_ids, "candidate_ids")
        if any(
            item.observation_id != self.observation.observation_id
            for item in self.candidates
        ):
            raise ValueError("Every candidate must reference the result observation.")
        if self.status == "success" and (not self.candidates or self.failures):
            raise ValueError("success requires candidates and no failures.")
        if self.status == "no_results" and (self.candidates or self.failures):
            raise ValueError("no_results cannot contain candidates or failures.")
        if self.status == "partial_failure" and (
            not self.candidates or not self.failures
        ):
            raise ValueError("partial_failure requires candidates and failures.")
        if self.status == "failed" and (self.candidates or not self.failures):
            raise ValueError("failed requires failures and no candidates.")


@dataclass(frozen=True)
class CandidateAssessment:
    candidate_id: str
    candidate_kind: str
    matched_constraint_ids: tuple[str, ...]
    conflicting_constraint_ids: tuple[str, ...]
    unresolved_constraint_ids: tuple[str, ...]
    expired: bool
    summary: str

    def __post_init__(self) -> None:
        for field_name in ("candidate_id", "candidate_kind", "summary"):
            require_non_empty_string(getattr(self, field_name), field_name)
        for field_name in (
            "matched_constraint_ids",
            "conflicting_constraint_ids",
            "unresolved_constraint_ids",
        ):
            require_unique_non_empty_strings(getattr(self, field_name), field_name)
        all_ids = (
            self.matched_constraint_ids
            + self.conflicting_constraint_ids
            + self.unresolved_constraint_ids
        )
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("A constraint cannot have multiple assessment outcomes.")
        if not isinstance(self.expired, bool):
            raise ValueError("expired must be a bool.")


@dataclass(frozen=True)
class TravelComparison:
    comparison_id: str
    trip_id: str
    observation_ids: tuple[str, ...]
    assessments: tuple[CandidateAssessment, ...]
    empty_observation_ids: tuple[str, ...]
    failures: tuple[ProviderFailure, ...]
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("comparison_id", "trip_id", "created_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        require_unique_non_empty_strings(self.observation_ids, "observation_ids")
        if not self.observation_ids:
            raise ValueError("observation_ids must not be empty.")
        require_unique_non_empty_strings(
            self.empty_observation_ids, "empty_observation_ids"
        )
        if any(item not in self.observation_ids for item in self.empty_observation_ids):
            raise ValueError("empty_observation_ids must belong to observation_ids.")
        if not isinstance(self.assessments, tuple) or any(
            not isinstance(item, CandidateAssessment) for item in self.assessments
        ):
            raise ValueError("assessments must contain CandidateAssessment values.")
        assessment_ids = tuple(item.candidate_id for item in self.assessments)
        require_unique_non_empty_strings(assessment_ids, "assessment_candidate_ids")
        if not isinstance(self.failures, tuple) or any(
            not isinstance(item, ProviderFailure) for item in self.failures
        ):
            raise ValueError("failures must contain ProviderFailure values.")


@dataclass(frozen=True)
class ItineraryDraft:
    draft_id: str
    trip_id: str
    candidate_ids: tuple[str, ...]
    summary: str
    version: int
    created_at: str
    comparison_id: str | None = None
    observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("draft_id", "trip_id", "summary", "created_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        require_unique_non_empty_strings(
            self.candidate_ids, "candidate_ids"
        )
        if not self.candidate_ids:
            raise ValueError("candidate_ids must not be empty.")
        _require_positive_integer(self.version, "version")
        if self.comparison_id is not None:
            require_non_empty_string(self.comparison_id, "comparison_id")
        require_unique_non_empty_strings(self.observation_ids, "observation_ids")


@dataclass(frozen=True)
class Itinerary:
    itinerary_id: str
    destination: str
    transport: str
    lodging: str
    summary: str
    observed_at: str
    expires_at: str
    provenance: str
    created_at: str
    trip_id: str | None = None
    draft_id: str | None = None
    idempotency_key: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        for field_name in (
            "itinerary_id",
            "destination",
            "transport",
            "lodging",
            "summary",
            "observed_at",
            "expires_at",
            "provenance",
            "created_at",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        for field_name in ("trip_id", "draft_id", "idempotency_key"):
            value = getattr(self, field_name)
            if value is not None:
                require_non_empty_string(value, field_name)
        _require_positive_integer(self.version, "version")


@dataclass(frozen=True)
class ItineraryItem:
    item_id: str
    itinerary_id: str
    day_number: int
    title: str
    item_type: str
    starts_at: str | None
    ends_at: str | None
    created_at: str
    source_candidate_id: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "item_id",
            "itinerary_id",
            "title",
            "item_type",
            "created_at",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_positive_integer(self.day_number, "day_number")
        for field_name in ("source_candidate_id", "notes"):
            value = getattr(self, field_name)
            if value is not None:
                require_non_empty_string(value, field_name)
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("starts_at and ends_at must both be set or both be None.")
        if self.starts_at is None:
            return
        starts_at = _parse_datetime(self.starts_at, "starts_at")
        ends_at = _parse_datetime(self.ends_at, "ends_at")
        try:
            has_invalid_range = ends_at <= starts_at
        except TypeError as exc:
            raise ValueError(
                "starts_at and ends_at must use compatible timezone information."
            ) from exc
        if has_invalid_range:
            raise ValueError("ends_at must be later than starts_at.")


@dataclass(frozen=True)
class TravelDecision:
    decision_id: str
    trip_id: str
    kind: str
    selected_candidate_ids: tuple[str, ...]
    rationale: str
    decided_at: str
    itinerary_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "trip_id", "rationale", "decided_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_supported_value(self.kind, "kind", TRAVEL_DECISION_KINDS)
        require_unique_non_empty_strings(
            self.selected_candidate_ids, "selected_candidate_ids"
        )
        if not self.selected_candidate_ids:
            raise ValueError("selected_candidate_ids must not be empty.")
        if self.itinerary_id is not None:
            require_non_empty_string(self.itinerary_id, "itinerary_id")


@dataclass(frozen=True)
class ItinerarySaveResult:
    itinerary: Itinerary
    items: tuple[ItineraryItem, ...]
    decision: TravelDecision

    def __post_init__(self) -> None:
        if not isinstance(self.itinerary, Itinerary):
            raise ValueError("itinerary must be an Itinerary.")
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("items must be a non-empty tuple.")
        if any(not isinstance(item, ItineraryItem) for item in self.items):
            raise ValueError("items must contain ItineraryItem values.")
        if any(item.itinerary_id != self.itinerary.itinerary_id for item in self.items):
            raise ValueError("Every item must belong to the saved itinerary.")
        if not isinstance(self.decision, TravelDecision):
            raise ValueError("decision must be a TravelDecision.")
        if self.decision.itinerary_id != self.itinerary.itinerary_id:
            raise ValueError("decision must belong to the saved itinerary.")


@dataclass(frozen=True)
class TravelPlanningSnapshot:
    trip_id: str
    title: str
    status: str
    trip_version: int
    constraint_kinds: tuple[str, ...]
    missing_constraint_kinds: tuple[str, ...]
    candidate_coverage: tuple[str, ...]
    saved_itinerary_count: int
    latest_itinerary_version: int | None
    pending_decision_kinds: tuple[str, ...]
    updated_at: str

    def __post_init__(self) -> None:
        for field_name in ("trip_id", "title", "updated_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_supported_value(self.status, "status", TRIP_STATUSES)
        _require_positive_integer(self.trip_version, "trip_version")
        for field_name in (
            "constraint_kinds",
            "missing_constraint_kinds",
            "candidate_coverage",
            "pending_decision_kinds",
        ):
            require_unique_non_empty_strings(getattr(self, field_name), field_name)
        if (
            not isinstance(self.saved_itinerary_count, int)
            or isinstance(self.saved_itinerary_count, bool)
            or self.saved_itinerary_count < 0
        ):
            raise ValueError("saved_itinerary_count must be a non-negative integer.")
        if self.latest_itinerary_version is not None:
            _require_positive_integer(
                self.latest_itinerary_version, "latest_itinerary_version"
            )


@dataclass(frozen=True)
class TravelContextCandidate:
    candidate_id: str
    item_kind: str
    content: str
    provenance: str
    estimated_chars: int
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "item_kind",
            "content",
            "provenance",
            "created_at",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_positive_integer(self.estimated_chars, "estimated_chars")


@dataclass(frozen=True)
class TravelPreferenceCandidate:
    candidate_id: str
    preference_kind: str
    value: str
    provenance: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)
