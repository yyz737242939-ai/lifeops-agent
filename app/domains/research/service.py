"""Request-local Research workflow service."""

from __future__ import annotations

from app.domains.research.models import ExternalObservation, ResearchSource
from app.domains.research.ports import ResearchSourcePort
from app.domains.research.repository import ResearchRepository


class ResearchService:
    """Keep fetched observations temporary until an authorized save Tool runs."""

    def __init__(
        self,
        source_port: ResearchSourcePort,
        repository: ResearchRepository,
    ) -> None:
        self._source_port = source_port
        self._repository = repository
        self._observations: dict[str, ExternalObservation] = {}

    def fetch_source(self, source_key: str) -> ExternalObservation:
        observation = self._source_port.fetch(source_key)
        self._observations[observation.observation_id] = observation
        return observation

    def save_source(self, observation_id: str) -> ResearchSource:
        try:
            observation = self._observations[observation_id]
        except KeyError as exc:
            raise ValueError("observation_id is not available in this request.") from exc
        return self._repository.save_source(observation)
