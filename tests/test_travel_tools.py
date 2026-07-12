from __future__ import annotations

import unittest

from app.domains.travel.ports import FixtureTravelOptionPort
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import (
    SAVE_ITINERARY_TOOL,
    SEARCH_OPTIONS_TOOL,
    build_travel_tools,
)
from app.policy.models import PolicyAction, PolicyDecision
from app.storage.unit_of_work import SqliteUnitOfWork
from app.tools.authorization import resolve_allowed_tools
from app.tools.gateway import ToolGateway
from app.tools.models import AllowedToolSet, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import create_test_connection


class TravelToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        service = TravelService(
            FixtureTravelOptionPort(
                {
                    "Tokyo": {
                        "transport": "Fixture flight SHA-HND",
                        "lodging": "Fixture hotel in Shinjuku",
                        "summary": "A planning-only fixture option; no booking was made.",
                    }
                }
            ),
            TravelRepository(self.conn),
        )
        self.registry = ToolRegistry(build_travel_tools(service))
        self.gateway = ToolGateway(self.registry)

    def tearDown(self) -> None:
        self.conn.close()

    def test_search_is_temporary_then_confirmed_save_persists_itinerary(self) -> None:
        search = self.gateway.execute(
            ToolCall(
                "call_search",
                SEARCH_OPTIONS_TOOL,
                {"destination": "Tokyo"},
            ),
            self._allowed("external_read"),
        )

        self.assertEqual(search.status, ToolCallStatus.SUCCEEDED)
        self.assertIn("no booking", str(search.output["summary"]))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            0,
        )
        save_call = ToolCall(
            "call_save",
            SAVE_ITINERARY_TOOL,
            {"option_id": str(search.output["option_id"])},
        )

        confirmation = self.gateway.execute(
            save_call,
            self._allowed("write"),
        )
        self.assertEqual(
            confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION
        )

        with SqliteUnitOfWork(self.conn):
            saved = self.gateway.execute(
                save_call,
                self._allowed("write"),
                confirmed_tool_name=SAVE_ITINERARY_TOOL,
            )

        self.assertEqual(saved.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(saved.evidence[0].evidence_type, "travel_itinerary_saved")
        row = self.conn.execute(
            "SELECT destination, provenance, summary FROM travel_itineraries"
        ).fetchone()
        self.assertEqual(row["destination"], "Tokyo")
        self.assertEqual(row["provenance"], "fixture:travel:Tokyo")
        self.assertIn("no booking", row["summary"])

    def test_unknown_destination_and_option_fail_closed(self) -> None:
        unknown_destination = self.gateway.execute(
            ToolCall(
                "call_search",
                SEARCH_OPTIONS_TOOL,
                {"destination": "Unknown"},
            ),
            self._allowed("external_read"),
        )
        unknown_option = self.gateway.execute(
            ToolCall(
                "call_save",
                SAVE_ITINERARY_TOOL,
                {"option_id": "travel-option_unknown"},
            ),
            self._allowed("write"),
            confirmed_tool_name=SAVE_ITINERARY_TOOL,
        )

        self.assertEqual(unknown_destination.status, ToolCallStatus.FAILED)
        self.assertEqual(unknown_option.status, ToolCallStatus.FAILED)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            0,
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
