from __future__ import annotations

import unittest

from app.domains.travel.models import (
    ExternalLookupResult,
    ExternalObservationRef,
    PlaceCandidate,
    ProviderFailure,
)
from app.domains.travel.ports import (
    CalendarAvailabilityPort,
    CalendarAvailabilityQuery,
    LodgingSearchPort,
    LodgingSearchQuery,
    PlaceSearchPort,
    PlaceSearchQuery,
    TransportSearchPort,
    TransportSearchQuery,
    WeatherInformationPort,
    WeatherInformationQuery,
)


class TravelPortsContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.observation = ExternalObservationRef(
            observation_id="observation_places_tokyo",
            provider="fixture-place",
            source_ref="fixture:travel:places:tokyo",
            observed_at="2026-07-13T00:00:00+00:00",
            expires_at="2026-07-13T01:00:00+00:00",
            provenance="fixture:travel:places:tokyo:v1",
        )
        self.place = PlaceCandidate(
            candidate_id="place_sensoji",
            observation_id=self.observation.observation_id,
            destination="Tokyo",
            name="Senso-ji",
            category="temple",
            summary="Fixture-backed place candidate.",
        )

    def test_five_ports_expose_distinct_typed_operations(self) -> None:
        self.assertTrue(hasattr(CalendarAvailabilityPort, "check_availability"))
        self.assertTrue(hasattr(WeatherInformationPort, "get_weather"))
        self.assertTrue(hasattr(TransportSearchPort, "search_transport"))
        self.assertTrue(hasattr(LodgingSearchPort, "search_lodging"))
        self.assertTrue(hasattr(PlaceSearchPort, "search_places"))

        CalendarAvailabilityQuery(
            "2026-10-01T00:00:00+09:00",
            "2026-10-03T00:00:00+09:00",
            "Asia/Tokyo",
            120,
        )
        WeatherInformationQuery("Tokyo", "2026-10-01", "2026-10-03")
        TransportSearchQuery("Shanghai", "Tokyo", "2026-10-01", 1)
        LodgingSearchQuery("Tokyo", "2026-10-01", "2026-10-03", 1)
        PlaceSearchQuery("Tokyo", "historic places")

    def test_lookup_statuses_have_unambiguous_candidate_failure_shapes(self) -> None:
        success = ExternalLookupResult(
            "success", self.observation, (self.place,)
        )
        no_results = ExternalLookupResult("no_results", self.observation, ())
        failure = ProviderFailure(
            provider="fixture-place",
            code="timeout",
            message="Fixture timeout.",
            retryable=True,
        )
        partial = ExternalLookupResult(
            "partial_failure", self.observation, (self.place,), (failure,)
        )
        failed = ExternalLookupResult(
            "failed", self.observation, (), (failure,)
        )

        self.assertEqual(success.candidates, (self.place,))
        self.assertEqual(no_results.candidates, ())
        self.assertTrue(partial.failures[0].retryable)
        self.assertEqual(failed.status, "failed")

    def test_candidate_cannot_claim_another_observation(self) -> None:
        forged = PlaceCandidate(
            candidate_id="place_forged",
            observation_id="observation_other",
            destination="Tokyo",
            name="Forged",
            category="other",
            summary="Invalid provenance link.",
        )

        with self.assertRaisesRegex(ValueError, "result observation"):
            ExternalLookupResult("success", self.observation, (forged,))

    def test_status_and_failure_contract_reject_ambiguous_results(self) -> None:
        failure = ProviderFailure(
            provider="fixture-place",
            code="rate_limit",
            message="Fixture rate limit.",
            retryable=True,
        )

        with self.assertRaisesRegex(ValueError, "success requires"):
            ExternalLookupResult(
                "success", self.observation, (self.place,), (failure,)
            )
        with self.assertRaisesRegex(ValueError, "partial_failure requires"):
            ExternalLookupResult(
                "partial_failure", self.observation, (self.place,), ()
            )
        with self.assertRaisesRegex(ValueError, "failed requires"):
            ExternalLookupResult("failed", self.observation, (), ())

    def test_query_counts_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            TransportSearchQuery("Shanghai", "Tokyo", "2026-10-01", 0)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            LodgingSearchQuery("Tokyo", "2026-10-01", "2026-10-03", 0)


if __name__ == "__main__":
    unittest.main()
