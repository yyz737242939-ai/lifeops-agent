"""Research external source ports and deterministic fixture adapter."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Protocol

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.research.models import ExternalObservation


class ResearchSourcePort(Protocol):
    def fetch(self, source_key: str) -> ExternalObservation:
        ...


class FixtureResearchSourcePort:
    """Fetch only explicitly declared fixture source keys."""

    def __init__(self, sources: Mapping[str, Mapping[str, str]]) -> None:
        self._sources = {key: dict(value) for key, value in sources.items()}

    def fetch(self, source_key: str) -> ExternalObservation:
        try:
            source = self._sources[source_key]
        except KeyError as exc:
            raise ValueError("source_key is not declared by the fixture adapter.") from exc
        title = source["title"]
        url = source["url"]
        summary = source["summary"]
        return ExternalObservation(
            observation_id=new_id("observation"),
            source_key=source_key,
            title=title,
            url=url,
            summary=summary,
            content_hash=sha256(summary.encode("utf-8")).hexdigest(),
            fetched_at=utc_now_iso(),
            provenance=f"fixture:{source_key}",
        )
