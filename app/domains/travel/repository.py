"""SQLite repository for durable Travel facts."""

from __future__ import annotations

import json
import sqlite3

from app.common.errors import StorageError
from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.references import KnowledgeReference
from app.domains.travel.models import (
    Itinerary,
    ItineraryItem,
    ItinerarySaveResult,
    TravelConstraint,
    TravelDecision,
    TravelKnowledgeReference,
    Trip,
)


class TravelRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_trip(self, title: str) -> Trip:
        now = utc_now_iso()
        trip = Trip(new_id("trip"), title, "active", 1, now, now)
        self._execute(
            """INSERT INTO trips
               (id, title, status, version, created_at, updated_at, archived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                trip.trip_id,
                trip.title,
                trip.status,
                trip.version,
                trip.created_at,
                trip.updated_at,
                trip.archived_at,
            ),
            "travel_trip_create_failed",
        )
        return trip

    def get_trip(self, trip_id: str) -> Trip:
        row = self._conn.execute(
            """SELECT id, title, status, version, created_at, updated_at, archived_at
               FROM trips WHERE id = ?""",
            (trip_id,),
        ).fetchone()
        if row is None:
            raise ValueError("trip_id does not exist.")
        return self._trip_from_row(row)

    def list_trips(self, *, include_archived: bool = False) -> tuple[Trip, ...]:
        if include_archived:
            rows = self._conn.execute(
                """SELECT id, title, status, version, created_at, updated_at, archived_at
                   FROM trips ORDER BY created_at, id"""
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, title, status, version, created_at, updated_at, archived_at
                   FROM trips WHERE status = 'active' ORDER BY created_at, id"""
            ).fetchall()
        return tuple(self._trip_from_row(row) for row in rows)

    def replace_constraints(
        self,
        trip_id: str,
        constraints: tuple[tuple[str, str], ...],
        *,
        expected_version: int,
    ) -> tuple[TravelConstraint, ...]:
        trip = self.get_trip(trip_id)
        if trip.status != "active":
            raise ValueError("Archived trips cannot be updated.")
        if trip.version != expected_version:
            raise ValueError("Trip version conflict.")
        if len(set(constraints)) != len(constraints):
            raise ValueError("constraints must not contain duplicates.")
        now = utc_now_iso()
        models = tuple(
            TravelConstraint(new_id("travel-constraint"), trip_id, kind, value, now, now)
            for kind, value in constraints
        )
        try:
            self._conn.execute("DELETE FROM travel_constraints WHERE trip_id = ?", (trip_id,))
            self._conn.executemany(
                """INSERT INTO travel_constraints
                   (id, trip_id, kind, value, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    (
                        item.constraint_id,
                        item.trip_id,
                        item.kind,
                        item.value,
                        item.created_at,
                        item.updated_at,
                    )
                    for item in models
                ),
            )
            cursor = self._conn.execute(
                """UPDATE trips SET version = version + 1, updated_at = ?
                   WHERE id = ? AND status = 'active' AND version = ?""",
                (now, trip_id, expected_version),
            )
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to replace Travel constraints.",
                code="travel_constraints_replace_failed",
            ) from exc
        if cursor.rowcount != 1:
            raise ValueError("Trip version conflict.")
        return self.list_constraints(trip_id)

    def list_constraints(self, trip_id: str) -> tuple[TravelConstraint, ...]:
        self.get_trip(trip_id)
        rows = self._conn.execute(
            """SELECT id, trip_id, kind, value, created_at, updated_at
               FROM travel_constraints
               WHERE trip_id = ? ORDER BY kind, created_at, id""",
            (trip_id,),
        ).fetchall()
        return tuple(
            TravelConstraint(
                str(row["id"]),
                str(row["trip_id"]),
                str(row["kind"]),
                str(row["value"]),
                str(row["created_at"]),
                str(row["updated_at"]),
            )
            for row in rows
        )

    def archive_trip(self, trip_id: str, *, expected_version: int) -> Trip:
        trip = self.get_trip(trip_id)
        if trip.status == "archived":
            return trip
        if trip.version != expected_version:
            raise ValueError("Trip version conflict.")
        now = utc_now_iso()
        try:
            cursor = self._conn.execute(
                """UPDATE trips
                   SET status = 'archived', version = version + 1,
                       updated_at = ?, archived_at = ?
                   WHERE id = ? AND status = 'active' AND version = ?""",
                (now, now, trip_id, expected_version),
            )
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to archive Travel trip.", code="travel_trip_archive_failed"
            ) from exc
        if cursor.rowcount != 1:
            raise ValueError("Trip version conflict.")
        return self.get_trip(trip_id)

    def add_knowledge_reference(
        self, trip_id: str, reference: KnowledgeReference
    ) -> TravelKnowledgeReference:
        self.get_trip(trip_id)
        existing = self._conn.execute(
            """SELECT id, trip_id, domain, item_kind, item_id, created_at
               FROM travel_knowledge_refs
               WHERE trip_id = ? AND domain = ? AND item_kind = ? AND item_id = ?""",
            (trip_id, reference.domain, reference.item_kind, reference.item_id),
        ).fetchone()
        if existing is not None:
            return self._knowledge_reference_from_row(existing)
        saved = TravelKnowledgeReference(trip_id, reference, utc_now_iso())
        self._execute(
            """INSERT INTO travel_knowledge_refs
               (id, trip_id, domain, item_kind, item_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                reference.reference_id,
                trip_id,
                reference.domain,
                reference.item_kind,
                reference.item_id,
                saved.created_at,
            ),
            "travel_knowledge_reference_create_failed",
        )
        return saved

    def list_knowledge_references(
        self, trip_id: str
    ) -> tuple[TravelKnowledgeReference, ...]:
        self.get_trip(trip_id)
        rows = self._conn.execute(
            """SELECT id, trip_id, domain, item_kind, item_id, created_at
               FROM travel_knowledge_refs
               WHERE trip_id = ? ORDER BY created_at, id""",
            (trip_id,),
        ).fetchall()
        return tuple(self._knowledge_reference_from_row(row) for row in rows)

    def list_itineraries(self, trip_id: str) -> tuple[Itinerary, ...]:
        self.get_trip(trip_id)
        rows = self._conn.execute(
            """SELECT id, destination, transport, lodging, summary,
                      observed_at, expires_at, provenance, created_at,
                      trip_id, draft_id, idempotency_key, version
               FROM travel_itineraries
               WHERE trip_id = ? ORDER BY created_at, id""",
            (trip_id,),
        ).fetchall()
        return tuple(self._itinerary_from_row(row) for row in rows)

    def get_idempotent_itinerary_save(
        self, idempotency_key: str, draft_id: str
    ) -> ItinerarySaveResult | None:
        existing = self._conn.execute(
            """SELECT id, destination, transport, lodging, summary,
                      observed_at, expires_at, provenance, created_at,
                      trip_id, draft_id, idempotency_key, version
               FROM travel_itineraries WHERE idempotency_key = ?""",
            (idempotency_key,),
        ).fetchone()
        if existing is None:
            return None
        if str(existing["draft_id"]) != draft_id:
            raise StorageError(
                "Travel itinerary idempotency key belongs to another draft.",
                code="travel_itinerary_idempotency_conflict",
            )
        return self._load_itinerary_bundle(existing)

    def save_itinerary_bundle(
        self,
        itinerary: Itinerary,
        items: tuple[ItineraryItem, ...],
        decision: TravelDecision,
    ) -> ItinerarySaveResult:
        existing = self.get_idempotent_itinerary_save(
            itinerary.idempotency_key, itinerary.draft_id
        )
        if existing is not None:
            return existing
        try:
            self._conn.execute(
                """
                INSERT INTO travel_itineraries (
                    id, destination, transport, lodging, summary,
                    observed_at, expires_at, provenance, created_at,
                    trip_id, draft_id, idempotency_key, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    itinerary.trip_id,
                    itinerary.draft_id,
                    itinerary.idempotency_key,
                    itinerary.version,
                ),
            )
            self._conn.executemany(
                """INSERT INTO travel_itinerary_items (
                       id, itinerary_id, day_number, title, item_type,
                       starts_at, ends_at, source_candidate_id, notes, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    (
                        item.item_id,
                        item.itinerary_id,
                        item.day_number,
                        item.title,
                        item.item_type,
                        item.starts_at,
                        item.ends_at,
                        item.source_candidate_id,
                        item.notes,
                        item.created_at,
                    )
                    for item in items
                ),
            )
            self._conn.execute(
                """INSERT INTO travel_decisions (
                       id, trip_id, itinerary_id, kind,
                       selected_candidate_ids_json, rationale, decided_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision.decision_id,
                    decision.trip_id,
                    decision.itinerary_id,
                    decision.kind,
                    json.dumps(decision.selected_candidate_ids),
                    decision.rationale,
                    decision.decided_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageError(
                "Travel itinerary idempotency conflict.",
                code="travel_itinerary_idempotency_conflict",
            ) from exc
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to save Travel itinerary.",
                code="travel_itinerary_save_failed",
            ) from exc
        return ItinerarySaveResult(itinerary, items, decision)

    def _load_itinerary_bundle(self, itinerary_row: sqlite3.Row) -> ItinerarySaveResult:
        itinerary = self._itinerary_from_row(itinerary_row)
        item_rows = self._conn.execute(
            """SELECT id, itinerary_id, day_number, title, item_type,
                      starts_at, ends_at, source_candidate_id, notes, created_at
               FROM travel_itinerary_items
               WHERE itinerary_id = ? ORDER BY day_number, id""",
            (itinerary.itinerary_id,),
        ).fetchall()
        items = tuple(
            ItineraryItem(
                item_id=str(row["id"]),
                itinerary_id=str(row["itinerary_id"]),
                day_number=int(row["day_number"]),
                title=str(row["title"]),
                item_type=str(row["item_type"]),
                starts_at=None if row["starts_at"] is None else str(row["starts_at"]),
                ends_at=None if row["ends_at"] is None else str(row["ends_at"]),
                created_at=str(row["created_at"]),
                source_candidate_id=(
                    None
                    if row["source_candidate_id"] is None
                    else str(row["source_candidate_id"])
                ),
                notes=None if row["notes"] is None else str(row["notes"]),
            )
            for row in item_rows
        )
        row = self._conn.execute(
            """SELECT id, trip_id, itinerary_id, kind,
                      selected_candidate_ids_json, rationale, decided_at
               FROM travel_decisions WHERE itinerary_id = ? AND kind = 'itinerary'""",
            (itinerary.itinerary_id,),
        ).fetchone()
        if row is None:
            raise StorageError(
                "Saved Travel itinerary decision is missing.",
                code="travel_itinerary_decision_missing",
            )
        raw_ids = json.loads(str(row["selected_candidate_ids_json"]))
        decision = TravelDecision(
            decision_id=str(row["id"]),
            trip_id=str(row["trip_id"]),
            kind=str(row["kind"]),
            selected_candidate_ids=tuple(str(item) for item in raw_ids),
            rationale=str(row["rationale"]),
            decided_at=str(row["decided_at"]),
            itinerary_id=str(row["itinerary_id"]),
        )
        return ItinerarySaveResult(itinerary, items, decision)

    def _execute(self, sql: str, params: tuple[object, ...], code: str) -> None:
        try:
            self._conn.execute(sql, params)
        except sqlite3.Error as exc:
            raise StorageError("Failed to write Travel fact.", code=code) from exc

    @staticmethod
    def _knowledge_reference_from_row(row: sqlite3.Row) -> TravelKnowledgeReference:
        return TravelKnowledgeReference(
            trip_id=str(row["trip_id"]),
            reference=KnowledgeReference(
                reference_id=str(row["id"]),
                domain=str(row["domain"]),
                item_kind=str(row["item_kind"]),
                item_id=str(row["item_id"]),
            ),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _trip_from_row(row: sqlite3.Row) -> Trip:
        return Trip(
            str(row["id"]),
            str(row["title"]),
            str(row["status"]),
            int(row["version"]),
            str(row["created_at"]),
            str(row["updated_at"]),
            None if row["archived_at"] is None else str(row["archived_at"]),
        )

    @staticmethod
    def _itinerary_from_row(row: sqlite3.Row) -> Itinerary:
        return Itinerary(
            itinerary_id=str(row["id"]),
            destination=str(row["destination"]),
            transport=str(row["transport"]),
            lodging=str(row["lodging"]),
            summary=str(row["summary"]),
            observed_at=str(row["observed_at"]),
            expires_at=str(row["expires_at"]),
            provenance=str(row["provenance"]),
            created_at=str(row["created_at"]),
            trip_id=None if row["trip_id"] is None else str(row["trip_id"]),
            draft_id=None if row["draft_id"] is None else str(row["draft_id"]),
            idempotency_key=(
                None if row["idempotency_key"] is None else str(row["idempotency_key"])
            ),
            version=int(row["version"]),
        )
