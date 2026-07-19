"""Deterministic fixture adapters for Travel external capability ports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generic, TypeVar

from app.domains.travel.models import (
    CalendarAvailabilityCandidate,
    ExternalLookupResult,
    ExternalObservationRef,
    LodgingCandidate,
    PlaceCandidate,
    ProviderFailure,
    TransportCandidate,
    WeatherInformationCandidate,
)
from app.domains.travel.ports import (
    CalendarAvailabilityQuery,
    LodgingSearchQuery,
    PlaceSearchQuery,
    TransportSearchQuery,
    WeatherInformationQuery,
)


CandidateT = TypeVar(
    "CandidateT",
    CalendarAvailabilityCandidate,
    WeatherInformationCandidate,
    TransportCandidate,
    LodgingCandidate,
    PlaceCandidate,
)


class _FixtureAdapter(Generic[CandidateT]):
    def __init__(
        self,
        fixture_path: Path,
        failure_fixture_path: Path,
        *,
        scenario: str = "success",
    ) -> None:
        self._fixture = _load_fixture(fixture_path)
        failures = _load_fixture(failure_fixture_path)
        cases = failures.get("cases")
        if not isinstance(cases, dict) or scenario not in cases:
            raise ValueError("Travel failure fixture does not declare scenario.")
        case = cases[scenario]
        if not isinstance(case, dict):
            raise ValueError("Travel failure fixture scenario must be an object.")
        self._scenario = scenario
        self._failure_case = case

    def _result(
        self, candidates: tuple[CandidateT, ...]
    ) -> ExternalLookupResult[CandidateT]:
        observation = self._observation()
        if self._scenario == "success":
            return ExternalLookupResult("success", observation, candidates)
        if self._scenario == "no_results":
            return ExternalLookupResult("no_results", observation, ())
        failure = ProviderFailure(
            provider=observation.provider,
            code=_string(self._failure_case, "code"),
            message=_string(self._failure_case, "message"),
            retryable=_boolean(self._failure_case, "retryable"),
        )
        if self._scenario == "partial_failure":
            return ExternalLookupResult(
                "partial_failure", observation, candidates, (failure,)
            )
        return ExternalLookupResult("failed", observation, (), (failure,))

    def _observation(self) -> ExternalObservationRef:
        raw = self._fixture.get("observation")
        if not isinstance(raw, dict):
            raise ValueError("Travel fixture observation must be an object.")
        expires_at = raw.get("expires_at")
        if self._scenario == "expired":
            expires_at = self._failure_case.get("expires_at")
        if expires_at is not None and not isinstance(expires_at, str):
            raise ValueError("Travel fixture expires_at must be a string or null.")
        return ExternalObservationRef(
            observation_id=_string(raw, "observation_id"),
            provider=_string(raw, "provider"),
            source_ref=_string(raw, "source_ref"),
            observed_at=_string(raw, "observed_at"),
            expires_at=expires_at,
            provenance=_string(raw, "provenance"),
        )

    def _candidate_rows(self) -> list[dict[str, Any]]:
        rows = self._fixture.get("candidates")
        if not isinstance(rows, list) or not rows:
            raise ValueError("Travel fixture candidates must be a non-empty list.")
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("Travel fixture candidates must contain objects.")
        return rows

    def _require_query(self, actual: dict[str, object]) -> None:
        expected = self._fixture.get("query")
        if not isinstance(expected, dict) or expected != actual:
            raise ValueError("query is not declared by the fixture adapter.")


class FixtureCalendarAvailabilityAdapter(
    _FixtureAdapter[CalendarAvailabilityCandidate]
):
    def check_availability(
        self, query: CalendarAvailabilityQuery
    ) -> ExternalLookupResult[CalendarAvailabilityCandidate]:
        self._require_query(
            {
                "starts_at": query.starts_at,
                "ends_at": query.ends_at,
                "timezone": query.timezone,
                "minimum_duration_minutes": query.minimum_duration_minutes,
            }
        )
        observation_id = self._observation().observation_id
        candidates = tuple(
            CalendarAvailabilityCandidate(
                _string(row, "candidate_id"),
                observation_id,
                _string(row, "starts_at"),
                _string(row, "ends_at"),
                _string(row, "timezone"),
            )
            for row in self._candidate_rows()
        )
        return self._result(candidates)


class FixtureWeatherInformationAdapter(_FixtureAdapter[WeatherInformationCandidate]):
    def get_weather(
        self, query: WeatherInformationQuery
    ) -> ExternalLookupResult[WeatherInformationCandidate]:
        self._require_query(
            {
                "location": query.location,
                "starts_on": query.starts_on,
                "ends_on": query.ends_on,
            }
        )
        observation_id = self._observation().observation_id
        candidates = tuple(
            WeatherInformationCandidate(
                _string(row, "candidate_id"),
                observation_id,
                _string(row, "location"),
                _string(row, "date"),
                _string(row, "condition"),
                _number(row, "temperature_min"),
                _number(row, "temperature_max"),
                _string(row, "temperature_unit"),
            )
            for row in self._candidate_rows()
        )
        return self._result(candidates)


class FixtureTransportSearchAdapter(_FixtureAdapter[TransportCandidate]):
    def search_transport(
        self, query: TransportSearchQuery
    ) -> ExternalLookupResult[TransportCandidate]:
        self._require_query(
            {
                "origin": query.origin,
                "destination": query.destination,
                "departs_on": query.departs_on,
                "traveler_count": query.traveler_count,
            }
        )
        observation_id = self._observation().observation_id
        candidates = tuple(
            TransportCandidate(
                _string(row, "candidate_id"),
                observation_id,
                _string(row, "origin"),
                _string(row, "destination"),
                _string(row, "mode"),
                _string(row, "departs_at"),
                _string(row, "arrives_at"),
                _integer(row, "price_minor"),
                _string(row, "currency"),
            )
            for row in self._candidate_rows()
        )
        return self._result(candidates)


class FixtureLodgingSearchAdapter(_FixtureAdapter[LodgingCandidate]):
    def search_lodging(
        self, query: LodgingSearchQuery
    ) -> ExternalLookupResult[LodgingCandidate]:
        self._require_query(
            {
                "destination": query.destination,
                "check_in": query.check_in,
                "check_out": query.check_out,
                "guest_count": query.guest_count,
            }
        )
        observation_id = self._observation().observation_id
        candidates = tuple(
            LodgingCandidate(
                _string(row, "candidate_id"),
                observation_id,
                _string(row, "destination"),
                _string(row, "name"),
                _string(row, "check_in"),
                _string(row, "check_out"),
                _integer(row, "price_minor"),
                _string(row, "currency"),
            )
            for row in self._candidate_rows()
        )
        return self._result(candidates)


class FixturePlaceSearchAdapter(_FixtureAdapter[PlaceCandidate]):
    def search_places(
        self, query: PlaceSearchQuery
    ) -> ExternalLookupResult[PlaceCandidate]:
        self._require_query(
            {"destination": query.destination, "query": query.query}
        )
        observation_id = self._observation().observation_id
        candidates = tuple(
            PlaceCandidate(
                _string(row, "candidate_id"),
                observation_id,
                _string(row, "destination"),
                _string(row, "name"),
                _string(row, "category"),
                _string(row, "summary"),
            )
            for row in self._candidate_rows()
        )
        return self._result(candidates)


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Travel fixture could not be loaded.") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("Travel fixture must use schema_version 1.")
    return raw


def _string(raw: dict[str, Any], field_name: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Travel fixture {field_name} must be a non-empty string.")
    return value


def _integer(raw: dict[str, Any], field_name: str) -> int:
    value = raw.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Travel fixture {field_name} must be an integer.")
    return value


def _number(raw: dict[str, Any], field_name: str) -> float:
    value = raw.get(field_name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Travel fixture {field_name} must be a number.")
    return float(value)


def _boolean(raw: dict[str, Any], field_name: str) -> bool:
    value = raw.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"Travel fixture {field_name} must be a bool.")
    return value
