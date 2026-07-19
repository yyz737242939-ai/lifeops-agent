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
from app.domains.travel.ports import (
    CalendarAvailabilityQuery,
    LodgingSearchQuery,
    PlaceSearchQuery,
    TransportSearchQuery,
    WeatherInformationQuery,
)


FIXTURE_ROOT = Path("tests/fixtures/travel")
FAILURES = FIXTURE_ROOT / "provider_failures.json"


class TravelFixtureAdaptersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = (
            (
                FixtureCalendarAvailabilityAdapter,
                "calendar_available.json",
                CalendarAvailabilityQuery(
                    "2026-10-01T00:00:00+09:00",
                    "2026-10-03T00:00:00+09:00",
                    "Asia/Tokyo",
                    120,
                ),
                "check_availability",
            ),
            (
                FixtureWeatherInformationAdapter,
                "weather_tokyo_october.json",
                WeatherInformationQuery("Tokyo", "2026-10-01", "2026-10-03"),
                "get_weather",
            ),
            (
                FixtureTransportSearchAdapter,
                "transport_shanghai_tokyo.json",
                TransportSearchQuery("Shanghai", "Tokyo", "2026-10-01", 1),
                "search_transport",
            ),
            (
                FixtureLodgingSearchAdapter,
                "lodging_tokyo.json",
                LodgingSearchQuery("Tokyo", "2026-10-01", "2026-10-03", 1),
                "search_lodging",
            ),
            (
                FixturePlaceSearchAdapter,
                "places_tokyo.json",
                PlaceSearchQuery("Tokyo", "historic places"),
                "search_places",
            ),
        )

    def test_all_five_adapters_return_deterministic_typed_success(self) -> None:
        for adapter_type, fixture_name, query, method_name in self.cases:
            with self.subTest(adapter=adapter_type.__name__):
                adapter = adapter_type(FIXTURE_ROOT / fixture_name, FAILURES)
                first = getattr(adapter, method_name)(query)
                second = getattr(adapter, method_name)(query)

                self.assertEqual(first, second)
                self.assertEqual(first.status, "success")
                self.assertTrue(first.candidates)
                self.assertTrue(first.observation.provenance.startswith("fixture:"))
                self.assertEqual(
                    first.candidates[0].observation_id,
                    first.observation.observation_id,
                )

    def test_every_adapter_supports_declared_failure_scenarios(self) -> None:
        expected = {
            "no_results": ("no_results", False, None),
            "timeout": ("failed", False, "timeout"),
            "rate_limit": ("failed", False, "rate_limit"),
            "expired": ("failed", False, "expired"),
            "partial_failure": ("partial_failure", True, "provider_error"),
        }
        for adapter_type, fixture_name, query, method_name in self.cases:
            for scenario, (status, has_candidates, failure_code) in expected.items():
                with self.subTest(adapter=adapter_type.__name__, scenario=scenario):
                    adapter = adapter_type(
                        FIXTURE_ROOT / fixture_name,
                        FAILURES,
                        scenario=scenario,
                    )
                    result = getattr(adapter, method_name)(query)

                    self.assertEqual(result.status, status)
                    self.assertEqual(bool(result.candidates), has_candidates)
                    if failure_code is None:
                        self.assertEqual(result.failures, ())
                    else:
                        self.assertEqual(result.failures[0].code, failure_code)

    def test_timeout_and_rate_limit_are_retryable(self) -> None:
        for scenario in ("timeout", "rate_limit"):
            adapter = FixturePlaceSearchAdapter(
                FIXTURE_ROOT / "places_tokyo.json",
                FAILURES,
                scenario=scenario,
            )
            result = adapter.search_places(
                PlaceSearchQuery("Tokyo", "historic places")
            )

            self.assertTrue(result.failures[0].retryable)

    def test_expired_scenario_uses_expired_observation_metadata(self) -> None:
        adapter = FixtureTransportSearchAdapter(
            FIXTURE_ROOT / "transport_shanghai_tokyo.json",
            FAILURES,
            scenario="expired",
        )
        result = adapter.search_transport(
            TransportSearchQuery("Shanghai", "Tokyo", "2026-10-01", 1)
        )

        self.assertLess(result.observation.expires_at, result.observation.observed_at)
        self.assertEqual(result.failures[0].code, "expired")

    def test_adapter_rejects_query_outside_declared_fixture_scope(self) -> None:
        adapter = FixturePlaceSearchAdapter(
            FIXTURE_ROOT / "places_tokyo.json", FAILURES
        )

        with self.assertRaisesRegex(ValueError, "not declared"):
            adapter.search_places(PlaceSearchQuery("Osaka", "historic places"))


if __name__ == "__main__":
    unittest.main()
