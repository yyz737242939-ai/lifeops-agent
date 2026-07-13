from __future__ import annotations

import unittest
from pathlib import Path

from app.common.errors import StorageError
from app.domains.travel.adapters import (
    FixtureCalendarAvailabilityAdapter,
    FixtureLodgingSearchAdapter,
    FixturePlaceSearchAdapter,
    FixtureTransportSearchAdapter,
    FixtureWeatherInformationAdapter,
)
from app.domains.travel.ports import PlaceSearchQuery
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import (
    BUILD_ITINERARY_DRAFT_TOOL,
    COMPARE_OPTIONS_TOOL,
    SEARCH_LODGING_TOOL,
    SEARCH_PLACES_TOOL,
    SEARCH_TRANSPORT_TOOL,
    SAVE_ITINERARY_TOOL,
    build_travel_tools,
)
from app.policy.models import PolicyAction, PolicyDecision
from app.storage.unit_of_work import SqliteUnitOfWork
from app.tools.authorization import resolve_allowed_tools
from app.tools.gateway import ToolGateway
from app.tools.models import ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import create_test_connection


class TravelPlanningWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        root = Path("tests/fixtures/travel")
        failures = root / "provider_failures.json"
        self.service = TravelService(
            TravelRepository(self.conn),
            calendar_port=FixtureCalendarAvailabilityAdapter(
                root / "calendar_available.json", failures
            ),
            weather_port=FixtureWeatherInformationAdapter(
                root / "weather_tokyo_october.json", failures
            ),
            transport_port=FixtureTransportSearchAdapter(
                root / "transport_shanghai_tokyo.json", failures
            ),
            lodging_port=FixtureLodgingSearchAdapter(
                root / "lodging_tokyo.json", failures
            ),
            place_port=FixturePlaceSearchAdapter(
                root / "places_tokyo.json", failures
            ),
        )
        self.registry = ToolRegistry(build_travel_tools(self.service))
        self.gateway = ToolGateway(self.registry)
        with SqliteUnitOfWork(self.conn):
            self.trip = self.service.create_trip("Tokyo planning")
            self.service.update_trip_constraints(
                self.trip.trip_id,
                (("destination", "Tokyo"), ("budget", "CNY 12000")),
                expected_version=1,
            )

    def tearDown(self) -> None:
        self.conn.close()

    def test_search_compare_and_versioned_draft_remain_request_local(self) -> None:
        external_results = self._search_candidates()
        observation_ids = [item.output["observation"]["observation_id"] for item in external_results]
        candidate_ids = [item.output["candidates"][0]["candidate_id"] for item in external_results]

        compared = self.gateway.execute(
            ToolCall(
                "compare",
                COMPARE_OPTIONS_TOOL,
                {"trip_id": self.trip.trip_id, "observation_ids": observation_ids},
            ),
            self._allowed("read"),
        )

        self.assertEqual(compared.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(len(compared.output["assessments"]), 3)
        self.assertTrue(
            all(not item["expired"] for item in compared.output["assessments"])
        )
        self.assertTrue(
            all(
                not item["conflicting_constraint_ids"]
                for item in compared.output["assessments"]
            )
        )

        first = self._build_draft(compared.output["comparison_id"], candidate_ids)
        second = self._build_draft(compared.output["comparison_id"], candidate_ids)

        self.assertEqual(first.output["version"], 1)
        self.assertEqual(second.output["version"], 2)
        self.assertEqual(first.output["observation_ids"], observation_ids)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            0,
        )

    def test_confirmed_draft_save_persists_items_decision_and_is_idempotent(self) -> None:
        external_results = self._search_candidates()
        observation_ids = [
            item.output["observation"]["observation_id"]
            for item in external_results
        ]
        candidate_ids = [
            item.output["candidates"][0]["candidate_id"]
            for item in external_results
        ]
        compared = self.gateway.execute(
            ToolCall(
                "compare_save",
                COMPARE_OPTIONS_TOOL,
                {"trip_id": self.trip.trip_id, "observation_ids": observation_ids},
            ),
            self._allowed("read"),
        )
        draft = self._build_draft(compared.output["comparison_id"], candidate_ids)
        save_call = ToolCall(
            "save_draft",
            SAVE_ITINERARY_TOOL,
            {
                "draft_id": draft.output["draft_id"],
                "idempotency_key": "save-tokyo-draft-v1",
            },
        )

        confirmation = self.gateway.execute(save_call, self._allowed("write"))
        self.assertEqual(
            confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            0,
        )

        with SqliteUnitOfWork(self.conn):
            first = self.gateway.execute(
                save_call,
                self._allowed("write"),
                confirmed_tool_name=SAVE_ITINERARY_TOOL,
            )
        with SqliteUnitOfWork(self.conn):
            second = self.gateway.execute(
                save_call,
                self._allowed("write"),
                confirmed_tool_name=SAVE_ITINERARY_TOOL,
            )

        self.assertEqual(first.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(second.output, first.output)
        self.assertEqual(first.evidence[0].evidence_type, "travel_itinerary_saved")
        self.assertEqual(len(first.output["item_ids"]), 3)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itinerary_items").fetchone()[0],
            3,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_decisions").fetchone()[0],
            1,
        )

    def test_idempotency_key_cannot_be_reused_for_another_draft(self) -> None:
        results = self._search_candidates()
        observation_ids = tuple(
            item.output["observation"]["observation_id"] for item in results
        )
        candidate_ids = tuple(
            item.output["candidates"][0]["candidate_id"] for item in results
        )
        comparison = self.service.compare_candidates(
            self.trip.trip_id, observation_ids
        )
        first_draft = self.service.build_itinerary_draft(
            comparison.comparison_id, candidate_ids, "First draft."
        )
        second_draft = self.service.build_itinerary_draft(
            comparison.comparison_id, candidate_ids, "Second draft."
        )
        with SqliteUnitOfWork(self.conn):
            self.service.save_itinerary(first_draft.draft_id, "same-key")

        with self.assertRaises(StorageError) as caught:
            with SqliteUnitOfWork(self.conn):
                self.service.save_itinerary(second_draft.draft_id, "same-key")

        self.assertEqual(
            caught.exception.code, "travel_itinerary_idempotency_conflict"
        )

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            1,
        )

    def test_compare_and_draft_reject_forged_ids(self) -> None:
        forged_comparison = self.gateway.execute(
            ToolCall(
                "compare_forged",
                COMPARE_OPTIONS_TOOL,
                {
                    "trip_id": self.trip.trip_id,
                    "observation_ids": ["observation_forged"],
                },
            ),
            self._allowed("read"),
        )
        self.assertEqual(forged_comparison.status, ToolCallStatus.FAILED)

        result = self._search_candidates()[0]
        compared = self.gateway.execute(
            ToolCall(
                "compare_valid",
                COMPARE_OPTIONS_TOOL,
                {
                    "trip_id": self.trip.trip_id,
                    "observation_ids": [
                        result.output["observation"]["observation_id"]
                    ],
                },
            ),
            self._allowed("read"),
        )
        forged_draft = self._build_draft(
            compared.output["comparison_id"], ["candidate_forged"]
        )
        self.assertEqual(forged_draft.status, ToolCallStatus.FAILED)

    def test_compare_schema_rejects_model_supplied_candidate_facts(self) -> None:
        result = self.gateway.execute(
            ToolCall(
                "compare_injected",
                COMPARE_OPTIONS_TOOL,
                {
                    "trip_id": self.trip.trip_id,
                    "observation_ids": ["observation_forged"],
                    "price_minor": 1,
                    "provenance": "model:forged",
                },
            ),
            self._allowed("read"),
        )

        self.assertEqual(result.status, ToolCallStatus.DENIED)
        self.assertEqual(result.error.code, "arguments_invalid")

    def test_conflicting_candidate_cannot_enter_draft(self) -> None:
        result = self._search_candidates()[2]
        with SqliteUnitOfWork(self.conn):
            trip = self.service.create_trip("Osaka planning")
            self.service.update_trip_constraints(
                trip.trip_id,
                (("destination", "Osaka"),),
                expected_version=1,
            )
        comparison = self.service.compare_candidates(
            trip.trip_id,
            (str(result.output["observation"]["observation_id"]),),
        )

        self.assertTrue(comparison.assessments[0].conflicting_constraint_ids)
        with self.assertRaisesRegex(ValueError, "Conflicting candidates"):
            self.service.build_itinerary_draft(
                comparison.comparison_id,
                (comparison.assessments[0].candidate_id,),
                "Invalid conflicting draft.",
            )

    def test_expired_candidate_cannot_enter_draft(self) -> None:
        root = Path("tests/fixtures/travel")
        expired_service = TravelService(
            TravelRepository(self.conn),
            place_port=FixturePlaceSearchAdapter(
                root / "places_tokyo.json",
                root / "provider_failures.json",
                scenario="partial_failure",
            ),
        )
        result = expired_service.search_places(
            PlaceSearchQuery("Tokyo", "historic places")
        )
        expired_result = result.__class__(
            result.status,
            result.observation.__class__(
                result.observation.observation_id,
                result.observation.provider,
                result.observation.source_ref,
                result.observation.observed_at,
                "2026-07-12T23:00:00+00:00",
                result.observation.provenance,
            ),
            result.candidates,
            result.failures,
        )
        expired_service._external_results[
            expired_result.observation.observation_id
        ] = expired_result
        comparison = expired_service.compare_candidates(
            self.trip.trip_id, (expired_result.observation.observation_id,)
        )

        self.assertTrue(comparison.assessments[0].expired)
        with self.assertRaisesRegex(ValueError, "Expired candidates"):
            expired_service.build_itinerary_draft(
                comparison.comparison_id,
                (comparison.assessments[0].candidate_id,),
                "Invalid expired draft.",
            )

    def _search_candidates(self):
        calls = (
            ToolCall(
                "transport",
                SEARCH_TRANSPORT_TOOL,
                {
                    "origin": "Shanghai",
                    "destination": "Tokyo",
                    "departs_on": "2026-10-01",
                    "traveler_count": 1,
                },
            ),
            ToolCall(
                "lodging",
                SEARCH_LODGING_TOOL,
                {
                    "destination": "Tokyo",
                    "check_in": "2026-10-01",
                    "check_out": "2026-10-03",
                    "guest_count": 1,
                },
            ),
            ToolCall(
                "places",
                SEARCH_PLACES_TOOL,
                {"destination": "Tokyo", "query": "historic places"},
            ),
        )
        return tuple(
            self.gateway.execute(call, self._allowed("external_read"))
            for call in calls
        )

    def _build_draft(self, comparison_id: str, candidate_ids: list[str]):
        return self.gateway.execute(
            ToolCall(
                "draft",
                BUILD_ITINERARY_DRAFT_TOOL,
                {
                    "comparison_id": comparison_id,
                    "candidate_ids": candidate_ids,
                    "summary": "Planning-only Tokyo itinerary draft.",
                },
            ),
            self._allowed("read"),
        )

    def _allowed(self, effect: str):
        return resolve_allowed_tools(
            ("travel",),
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_effects=[effect],
            ),
            self.registry,
        )


if __name__ == "__main__":
    unittest.main()
