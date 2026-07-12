"""Travel external option port and deterministic fixture adapter."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.common.ids import new_id
from app.domains.travel.models import CandidateOption


class TravelOptionPort(Protocol):
    def search(self, destination: str) -> CandidateOption:
        ...


class FixtureTravelOptionPort:
    """Return one explicitly declared fixture option per destination."""

    def __init__(self, options: Mapping[str, Mapping[str, str]]) -> None:
        self._options = {key: dict(value) for key, value in options.items()}

    def search(self, destination: str) -> CandidateOption:
        try:
            option = self._options[destination]
        except KeyError as exc:
            raise ValueError("destination is not declared by the fixture adapter.") from exc
        observed_at = datetime.now(UTC)
        return CandidateOption(
            option_id=new_id("travel-option"),
            destination=destination,
            transport=option["transport"],
            lodging=option["lodging"],
            summary=option["summary"],
            observed_at=observed_at.isoformat(),
            expires_at=(observed_at + timedelta(hours=1)).isoformat(),
            provenance=f"fixture:travel:{destination}",
        )
