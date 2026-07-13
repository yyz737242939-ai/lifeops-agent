from __future__ import annotations

import unittest
from pathlib import Path

from app.domains.travel.adapters import (
    FixtureCalendarAvailabilityAdapter,
    FixtureLodgingSearchAdapter,
    FixturePlaceSearchAdapter,
    FixtureTransportSearchAdapter,
    FixtureWeatherInformationAdapter,
)
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import (
    ARCHIVE_TRIP_TOOL,
    CHECK_CALENDAR_AVAILABILITY_TOOL,
    CREATE_TRIP_TOOL,
    GET_TRIP_TOOL,
    GET_WEATHER_TOOL,
    LIST_TRIPS_TOOL,
    SEARCH_LODGING_TOOL,
    SEARCH_PLACES_TOOL,
    SEARCH_TRANSPORT_TOOL,
    UPDATE_TRIP_CONSTRAINTS_TOOL,
    build_travel_tools,
)
from app.policy.models import PolicyAction, PolicyDecision
from app.storage.unit_of_work import SqliteUnitOfWork
from app.tools.authorization import resolve_allowed_tools
from app.tools.gateway import ToolGateway
from app.tools.models import AllowedToolSet, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import confirmed_action, create_test_connection


class TravelToolsTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.conn.close()

    def test_five_external_read_tools_return_typed_fixture_results(self) -> None:
        calls = (
            ToolCall(
                "calendar",
                CHECK_CALENDAR_AVAILABILITY_TOOL,
                {
                    "starts_at": "2026-10-01T00:00:00+09:00",
                    "ends_at": "2026-10-03T00:00:00+09:00",
                    "timezone": "Asia/Tokyo",
                    "minimum_duration_minutes": 120,
                },
            ),
            ToolCall(
                "weather",
                GET_WEATHER_TOOL,
                {
                    "location": "Tokyo",
                    "starts_on": "2026-10-01",
                    "ends_on": "2026-10-03",
                },
            ),
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

        for call in calls:
            with self.subTest(tool=call.tool_name):
                result = self.gateway.execute(call, self._allowed("external_read"))
                self.assertEqual(result.status, ToolCallStatus.SUCCEEDED)
                self.assertEqual(result.output["status"], "success")
                self.assertTrue(result.output["candidates"])
                self.assertIn("provenance", result.output["observation"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            0,
        )

    def test_aggregate_search_tool_is_not_registered(self) -> None:
        self.assertFalse(self.registry.contains("travel.search_options"))

    def test_trip_and_constraint_tools_follow_read_write_boundaries(self) -> None:
        create_call = ToolCall(
            "call_create_trip", CREATE_TRIP_TOOL, {"title": "Tokyo conference"}
        )
        confirmation = self.gateway.execute(create_call, self._allowed("write"))
        self.assertEqual(
            confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0], 0
        )

        with SqliteUnitOfWork(self.conn):
            created = self.gateway.execute(
                create_call,
                self._allowed("write"),
                confirmation=confirmed_action(create_call),
                run_id="run_test",
            )

        self.assertEqual(created.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(created.evidence[0].evidence_type, "travel_trip_created")
        trip_id = str(created.output["trip_id"])

        update_call = ToolCall(
            "call_update_constraints",
            UPDATE_TRIP_CONSTRAINTS_TOOL,
            {
                "trip_id": trip_id,
                "expected_version": 1,
                "constraints": [
                    {"kind": "destination", "value": "Tokyo"},
                    {"kind": "budget", "value": "CNY 12000"},
                ],
            },
        )
        with SqliteUnitOfWork(self.conn):
            updated = self.gateway.execute(
                update_call,
                self._allowed("write"),
                confirmation=confirmed_action(update_call),
                run_id="run_test",
            )

        self.assertEqual(updated.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(updated.output["version"], 2)
        self.assertEqual(
            updated.evidence[0].evidence_type, "travel_constraints_updated"
        )

        read = self.gateway.execute(
            ToolCall("call_get_trip", GET_TRIP_TOOL, {"trip_id": trip_id}),
            self._allowed("read"),
        )
        listed = self.gateway.execute(
            ToolCall("call_list_trips", LIST_TRIPS_TOOL, {}),
            self._allowed("read"),
        )
        self.assertEqual(read.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(len(read.output["constraints"]), 2)
        self.assertEqual(len(listed.output["trips"]), 1)

        archive_call = ToolCall(
            "call_archive_trip",
            ARCHIVE_TRIP_TOOL,
            {"trip_id": trip_id, "expected_version": 2},
        )
        with SqliteUnitOfWork(self.conn):
            archived = self.gateway.execute(
                archive_call,
                self._allowed("write"),
                confirmation=confirmed_action(archive_call),
                run_id="run_test",
            )

        self.assertEqual(archived.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(archived.output["status"], "archived")
        self.assertEqual(archived.evidence[0].evidence_type, "travel_trip_archived")

    def test_trip_write_tool_is_not_exposed_by_read_effect(self) -> None:
        result = self.gateway.execute(
            ToolCall("call_create_trip", CREATE_TRIP_TOOL, {"title": "Tokyo"}),
            self._allowed("read"),
        )

        self.assertEqual(result.status, ToolCallStatus.DENIED)
        self.assertEqual(result.error.code, "tool_not_allowed")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0], 0
        )

    def _allowed(self, effect: str) -> AllowedToolSet:
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
