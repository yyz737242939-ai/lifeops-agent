from __future__ import annotations

import unittest

from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.storage.unit_of_work import SqliteUnitOfWork
from tests.helpers import create_test_connection


class TravelRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repository = TravelRepository(self.conn)
        self.service = TravelService(
            self.repository,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_trip_constraints_version_and_archive_lifecycle(self) -> None:
        with SqliteUnitOfWork(self.conn):
            trip = self.service.create_trip("Tokyo conference")
            constraints = self.service.update_trip_constraints(
                trip.trip_id,
                (("destination", "Tokyo"), ("budget", "CNY 12000")),
                expected_version=1,
            )

        updated = self.service.get_trip(trip.trip_id)
        self.assertEqual(updated.version, 2)
        self.assertEqual(len(constraints), 2)
        self.assertEqual(self.service.get_trip_constraints(trip.trip_id), constraints)

        with self.assertRaisesRegex(ValueError, "version conflict"):
            self.service.update_trip_constraints(
                trip.trip_id,
                (("destination", "Osaka"),),
                expected_version=1,
            )

        with SqliteUnitOfWork(self.conn):
            archived = self.service.archive_trip(trip.trip_id, expected_version=2)

        self.assertEqual(archived.status, "archived")
        self.assertEqual(archived.version, 3)
        self.assertEqual(self.service.list_trips(), ())
        self.assertEqual(self.service.list_trips(include_archived=True), (archived,))
        with self.assertRaisesRegex(ValueError, "Archived trips"):
            self.service.update_trip_constraints(
                trip.trip_id,
                (("destination", "Kyoto"),),
                expected_version=3,
            )

    def test_archiving_an_archived_trip_is_idempotent(self) -> None:
        with SqliteUnitOfWork(self.conn):
            trip = self.service.create_trip("Tokyo")
        with SqliteUnitOfWork(self.conn):
            first = self.service.archive_trip(trip.trip_id, expected_version=1)
        with SqliteUnitOfWork(self.conn):
            second = self.service.archive_trip(trip.trip_id, expected_version=1)

        self.assertEqual(second, first)
        self.assertEqual(second.version, 2)

    def test_transaction_rolls_back_trip_and_constraints_together(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with SqliteUnitOfWork(self.conn):
                trip = self.service.create_trip("Rollback trip")
                self.service.update_trip_constraints(
                    trip.trip_id,
                    (("destination", "Tokyo"),),
                    expected_version=1,
                )
                raise RuntimeError("rollback")

        self.assertEqual(self.service.list_trips(include_archived=True), ())
        count = self.conn.execute(
            "SELECT COUNT(*) FROM travel_constraints"
        ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
