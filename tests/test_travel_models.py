from __future__ import annotations

import unittest

from app.domains.travel.models import (
    ExternalObservationRef,
    ItineraryDraft,
    ItineraryItem,
    TravelConstraint,
    TravelDecision,
    Trip,
)


class TravelModelsTest(unittest.TestCase):
    def test_active_and_archived_trip_states_are_distinct(self) -> None:
        active = Trip(
            trip_id="trip_tokyo",
            title="Tokyo conference",
            status="active",
            version=1,
            created_at="2026-07-12T10:00:00+08:00",
            updated_at="2026-07-12T10:00:00+08:00",
        )
        archived = Trip(
            trip_id="trip_tokyo",
            title="Tokyo conference",
            status="archived",
            version=2,
            created_at="2026-07-12T10:00:00+08:00",
            updated_at="2026-07-12T11:00:00+08:00",
            archived_at="2026-07-12T11:00:00+08:00",
        )

        self.assertEqual(active.status, "active")
        self.assertEqual(archived.status, "archived")
        with self.assertRaisesRegex(ValueError, "active trip"):
            Trip(
                trip_id="trip_invalid",
                title="Invalid",
                status="active",
                version=1,
                created_at="2026-07-12T10:00:00+08:00",
                updated_at="2026-07-12T10:00:00+08:00",
                archived_at="2026-07-12T11:00:00+08:00",
            )

    def test_constraint_kind_and_trip_version_are_validated(self) -> None:
        constraint = TravelConstraint(
            constraint_id="constraint_budget",
            trip_id="trip_tokyo",
            kind="budget",
            value="CNY 12000",
            created_at="2026-07-12T10:00:00+08:00",
            updated_at="2026-07-12T10:00:00+08:00",
        )

        self.assertEqual(constraint.kind, "budget")
        with self.assertRaisesRegex(ValueError, "positive integer"):
            Trip("trip", "Trip", "active", 0, "created", "updated")
        with self.assertRaisesRegex(ValueError, "kind must be one of"):
            TravelConstraint(
                "constraint", "trip", "booking", "value", "created", "updated"
            )

    def test_candidate_ids_flow_into_draft_and_decision_without_booking_state(self) -> None:
        draft = ItineraryDraft(
            draft_id="draft_tokyo_v1",
            trip_id="trip_tokyo",
            candidate_ids=("flight_1", "hotel_1"),
            summary="Planning-only itinerary draft.",
            version=1,
            created_at="2026-07-12T10:00:00+08:00",
        )
        decision = TravelDecision(
            decision_id="decision_transport",
            trip_id="trip_tokyo",
            kind="transport",
            selected_candidate_ids=("flight_1",),
            rationale="Fits the declared date and budget constraints.",
            decided_at="2026-07-12T10:30:00+08:00",
        )

        self.assertEqual(draft.candidate_ids, ("flight_1", "hotel_1"))
        self.assertEqual(decision.selected_candidate_ids, ("flight_1",))
        self.assertFalse(hasattr(draft, "booking_id"))
        self.assertFalse(hasattr(decision, "booking_status"))

    def test_draft_and_decision_reject_empty_or_duplicate_candidate_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            ItineraryDraft("draft", "trip", (), "summary", 1, "created")
        with self.assertRaisesRegex(ValueError, "must not contain duplicates"):
            TravelDecision(
                "decision",
                "trip",
                "lodging",
                ("hotel_1", "hotel_1"),
                "reason",
                "decided",
            )

    def test_observation_ref_and_itinerary_item_keep_provenance_link(self) -> None:
        observation = ExternalObservationRef(
            observation_id="weather_tokyo",
            provider="fixture-weather",
            source_ref="fixture:weather:tokyo",
            observed_at="2026-07-12T10:00:00+08:00",
            expires_at=None,
            provenance="fixture:travel:weather:tokyo",
        )
        item = ItineraryItem(
            item_id="item_flight",
            itinerary_id="itinerary_tokyo",
            day_number=1,
            title="Fly to Tokyo",
            item_type="transport",
            starts_at="2026-10-01T08:00:00+08:00",
            ends_at="2026-10-01T12:00:00+09:00",
            created_at="2026-07-12T10:00:00+08:00",
            source_candidate_id="flight_1",
        )

        self.assertEqual(observation.source_ref, "fixture:weather:tokyo")
        self.assertEqual(item.source_candidate_id, "flight_1")
        with self.assertRaisesRegex(ValueError, "later than"):
            ItineraryItem(
                "item",
                "itinerary",
                1,
                "Invalid",
                "place",
                "2026-10-01T12:00:00+09:00",
                "2026-10-01T11:00:00+09:00",
                "created",
            )


if __name__ == "__main__":
    unittest.main()
