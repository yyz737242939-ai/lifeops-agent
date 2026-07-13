"""Typed external capability ports for the Travel domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.common.validation import require_non_empty_string
from app.domains.travel.models import (
    CalendarAvailabilityCandidate,
    ExternalLookupResult,
    LodgingCandidate,
    PlaceCandidate,
    TransportCandidate,
    WeatherInformationCandidate,
)


def _require_positive_integer(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


@dataclass(frozen=True)
class CalendarAvailabilityQuery:
    starts_at: str
    ends_at: str
    timezone: str
    minimum_duration_minutes: int

    def __post_init__(self) -> None:
        for field_name in ("starts_at", "ends_at", "timezone"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_positive_integer(
            self.minimum_duration_minutes, "minimum_duration_minutes"
        )


@dataclass(frozen=True)
class WeatherInformationQuery:
    location: str
    starts_on: str
    ends_on: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class TransportSearchQuery:
    origin: str
    destination: str
    departs_on: str
    traveler_count: int

    def __post_init__(self) -> None:
        for field_name in ("origin", "destination", "departs_on"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_positive_integer(self.traveler_count, "traveler_count")


@dataclass(frozen=True)
class LodgingSearchQuery:
    destination: str
    check_in: str
    check_out: str
    guest_count: int

    def __post_init__(self) -> None:
        for field_name in ("destination", "check_in", "check_out"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_positive_integer(self.guest_count, "guest_count")


@dataclass(frozen=True)
class PlaceSearchQuery:
    destination: str
    query: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


class CalendarAvailabilityPort(Protocol):
    def check_availability(
        self, query: CalendarAvailabilityQuery
    ) -> ExternalLookupResult[CalendarAvailabilityCandidate]: ...


class WeatherInformationPort(Protocol):
    def get_weather(
        self, query: WeatherInformationQuery
    ) -> ExternalLookupResult[WeatherInformationCandidate]: ...


class TransportSearchPort(Protocol):
    def search_transport(
        self, query: TransportSearchQuery
    ) -> ExternalLookupResult[TransportCandidate]: ...


class LodgingSearchPort(Protocol):
    def search_lodging(
        self, query: LodgingSearchQuery
    ) -> ExternalLookupResult[LodgingCandidate]: ...


class PlaceSearchPort(Protocol):
    def search_places(
        self, query: PlaceSearchQuery
    ) -> ExternalLookupResult[PlaceCandidate]: ...
