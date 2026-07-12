"""Request-local Travel option workflow service."""

from __future__ import annotations

from app.domains.travel.models import CandidateOption, Itinerary
from app.domains.travel.ports import TravelOptionPort
from app.domains.travel.repository import TravelRepository


class TravelService:
    def __init__(
        self,
        option_port: TravelOptionPort,
        repository: TravelRepository,
    ) -> None:
        self._option_port = option_port
        self._repository = repository
        self._options: dict[str, CandidateOption] = {}

    def search_options(self, destination: str) -> CandidateOption:
        option = self._option_port.search(destination)
        self._options[option.option_id] = option
        return option

    def save_itinerary(self, option_id: str) -> Itinerary:
        try:
            option = self._options[option_id]
        except KeyError as exc:
            raise ValueError("option_id is not available in this request.") from exc
        return self._repository.save_itinerary(option)
