"""Research domain models for temporary observations and saved sources."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.validation import require_non_empty_string


@dataclass(frozen=True)
class ExternalObservation:
    observation_id: str
    source_key: str
    title: str
    url: str
    summary: str
    content_hash: str
    fetched_at: str
    provenance: str

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "source_key",
            "title",
            "url",
            "summary",
            "content_hash",
            "fetched_at",
            "provenance",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    source_key: str
    title: str
    url: str
    summary: str
    content_hash: str
    fetched_at: str
    provenance: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)
