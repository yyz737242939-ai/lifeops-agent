from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.domains.contracts import (
    DomainContextProvider,
    DomainMemoryCandidateProvider,
    DomainPlanningReadModel,
)
from app.domains.travel.models import (
    TravelContextCandidate,
    TravelPlanningSnapshot,
    TravelPreferenceCandidate,
)
from app.domains.travel.read_models import TravelReadService
from app.domains.travel.repository import TravelRepository
from app.storage.unit_of_work import SqliteUnitOfWork
from tests.helpers import create_test_connection


def _planner_consumer(
    read_model: DomainPlanningReadModel[TravelPlanningSnapshot], trip_id: str
) -> tuple[str, ...]:
    return read_model.get_planning_snapshot(trip_id).missing_constraint_kinds


def _react_context_consumer(
    provider: DomainContextProvider[TravelContextCandidate], trip_id: str
) -> tuple[str, ...]:
    return tuple(
        item.item_kind
        for item in provider.query_context_candidates(
            "Tokyo", 120, scope_id=trip_id
        )
    )


def _memory_consumer(
    provider: DomainMemoryCandidateProvider[TravelPreferenceCandidate], trip_id: str
) -> tuple[str, ...]:
    return tuple(
        item.preference_kind
        for item in provider.query_memory_candidates(
            "flight", 10, scope_id=trip_id
        )
    )


class TravelReadModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repository = TravelRepository(self.conn)
        self.read_service = TravelReadService(self.repository)
        raw = json.loads(
            Path("tests/fixtures/travel/history_seed.json").read_text(encoding="utf-8")
        )
        if raw.get("schema_version") != 1:
            raise ValueError("Invalid Travel history seed.")
        self.trips = []
        for entry in raw["trips"]:
            with SqliteUnitOfWork(self.conn):
                trip = self.repository.create_trip(entry["title"])
                self.repository.replace_constraints(
                    trip.trip_id,
                    tuple(tuple(item) for item in entry["constraints"]),
                    expected_version=1,
                )
            if entry.get("archived"):
                with SqliteUnitOfWork(self.conn):
                    self.repository.archive_trip(trip.trip_id, expected_version=2)
            self.trips.append(trip)

    def tearDown(self) -> None:
        self.conn.close()

    def test_fake_planner_and_dag_consumers_read_compact_persistent_coverage(self) -> None:
        trip_id = self.trips[0].trip_id
        snapshot = self.read_service.get_planning_snapshot(trip_id)

        self.assertEqual(_planner_consumer(self.read_service, trip_id), ())
        self.assertEqual(snapshot.candidate_coverage, ())
        self.assertEqual(snapshot.pending_decision_kinds, ("itinerary",))
        self.assertEqual(snapshot.saved_itinerary_count, 0)

    def test_context_and_memory_consumers_are_scoped_budgeted_and_explicit(self) -> None:
        trip_id = self.trips[0].trip_id
        context = self.read_service.query_context_candidates(
            "Tokyo", 120, scope_id=trip_id
        )

        self.assertLessEqual(sum(item.estimated_chars for item in context), 120)
        self.assertTrue(all(item.provenance for item in context))
        self.assertIn("constraint", _react_context_consumer(self.read_service, trip_id))
        self.assertEqual(_memory_consumer(self.read_service, trip_id), ("transport",))
        with self.assertRaisesRegex(ValueError, "scope_id"):
            self.read_service.query_context_candidates("Tokyo", 120)


if __name__ == "__main__":
    unittest.main()
