"""Travel domain models for temporary options and saved itineraries."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.validation import require_non_empty_string


@dataclass(frozen=True)
class CandidateOption:
    option_id: str
    destination: str
    transport: str
    lodging: str
    summary: str
    observed_at: str
    expires_at: str
    provenance: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


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

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)
