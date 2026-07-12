"""SQLite repository for confirmed Travel itineraries."""

from __future__ import annotations

import sqlite3

from app.common.errors import StorageError
from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.travel.models import CandidateOption, Itinerary


class TravelRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_itinerary(self, option: CandidateOption) -> Itinerary:
        itinerary = Itinerary(
            itinerary_id=new_id("itinerary"),
            destination=option.destination,
            transport=option.transport,
            lodging=option.lodging,
            summary=option.summary,
            observed_at=option.observed_at,
            expires_at=option.expires_at,
            provenance=option.provenance,
            created_at=utc_now_iso(),
        )
        try:
            self._conn.execute(
                """
                INSERT INTO travel_itineraries (
                    id, destination, transport, lodging, summary,
                    observed_at, expires_at, provenance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    itinerary.itinerary_id,
                    itinerary.destination,
                    itinerary.transport,
                    itinerary.lodging,
                    itinerary.summary,
                    itinerary.observed_at,
                    itinerary.expires_at,
                    itinerary.provenance,
                    itinerary.created_at,
                ),
            )
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to save Travel itinerary.",
                code="travel_itinerary_save_failed",
            ) from exc
        return itinerary
