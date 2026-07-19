from __future__ import annotations

import unittest

from app.domains.references import (
    KnowledgeReference,
    KnowledgeReferenceResolution,
    KnowledgeReferenceResolutionError,
)
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.storage.unit_of_work import SqliteUnitOfWork
from tests.helpers import create_test_connection


class _ResolvedReference:
    def resolve(self, reference: KnowledgeReference) -> KnowledgeReferenceResolution:
        return KnowledgeReferenceResolution(
            reference,
            "resolved",
            title="Tokyo research note",
            summary="Saved Research summary.",
            provenance="research:note",
        )


class _UnavailableReference:
    def resolve(self, reference: KnowledgeReference) -> KnowledgeReferenceResolution:
        raise KnowledgeReferenceResolutionError("reference_unavailable")


class TravelKnowledgeReferencesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.service = TravelService(TravelRepository(self.conn))
        with SqliteUnitOfWork(self.conn):
            self.trip = self.service.create_trip("Tokyo research trip")

    def tearDown(self) -> None:
        self.conn.close()

    def test_reference_stores_only_stable_ids_and_resolves_through_contract(self) -> None:
        with SqliteUnitOfWork(self.conn):
            first = self.service.add_knowledge_reference(
                self.trip.trip_id, "research", "note", "note_tokyo"
            )
        with SqliteUnitOfWork(self.conn):
            second = self.service.add_knowledge_reference(
                self.trip.trip_id, "research", "note", "note_tokyo"
            )

        view = self.service.get_trip_with_knowledge(
            self.trip.trip_id, _ResolvedReference()
        )
        self.assertEqual(second, first)
        self.assertEqual(view.references[0].status, "resolved")
        self.assertEqual(view.references[0].reference.item_id, "note_tokyo")
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(travel_knowledge_refs)")
        }
        self.assertNotIn("summary", columns)
        self.assertNotIn("body", columns)

    def test_resolver_failure_does_not_block_trip_body(self) -> None:
        with SqliteUnitOfWork(self.conn):
            self.service.add_knowledge_reference(
                self.trip.trip_id, "research", "brief", "brief_missing"
            )

        view = self.service.get_trip_with_knowledge(
            self.trip.trip_id, _UnavailableReference()
        )

        self.assertEqual(view.trip, self.trip)
        self.assertEqual(view.references[0].status, "unavailable")
        self.assertEqual(view.references[0].error_code, "reference_unavailable")

    def test_resolution_statuses_reject_ambiguous_payloads(self) -> None:
        reference = KnowledgeReference("ref_1", "research", "note", "note_1")

        with self.assertRaisesRegex(ValueError, "cannot contain error_code"):
            KnowledgeReferenceResolution(
                reference,
                "resolved",
                title="Note",
                summary="Summary",
                provenance="research:note",
                error_code="stale_error",
            )
        with self.assertRaisesRegex(ValueError, "cannot contain resolved content"):
            KnowledgeReferenceResolution(
                reference,
                "unavailable",
                title="Stale title",
                error_code="reference_unavailable",
            )


if __name__ == "__main__":
    unittest.main()
