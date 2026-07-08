from __future__ import annotations

import sqlite3
import unittest

from app.common.errors import SerializationError
from app.observability.events import LogRuntimeEvent, LogTraceEvent
from app.observability.trace_store import LogTraceStore
from app.storage.unit_of_work import SqliteUnitOfWork
from tests.helpers import create_test_connection, insert_test_run_record


class LogTraceStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        insert_test_run_record(self.conn)
        self.store = LogTraceStore(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_log_runtime_event_validates_required_fields(self) -> None:
        with self.assertRaises(ValueError):
            LogRuntimeEvent(run_id="", seq=1, event_type="runtime.started")
        with self.assertRaises(ValueError):
            LogRuntimeEvent(run_id="run_1", seq=0, event_type="runtime.started")
        with self.assertRaises(ValueError):
            LogRuntimeEvent(run_id="run_1", seq=1, event_type="")

    def test_append_and_list_trace_events_by_run_id_ordered_by_seq(self) -> None:
        second = LogTraceEvent(
            run_id="run_1",
            seq=2,
            event_type="policy.checked",
            payload={"allowed": True},
            id="evt_2",
            created_at="2026-07-08T00:00:02+00:00",
        )
        first = LogTraceEvent(
            run_id="run_1",
            seq=1,
            event_type="intent.classified",
            payload={"intent": "ask"},
            id="evt_1",
            created_at="2026-07-08T00:00:01+00:00",
        )

        with SqliteUnitOfWork(self.conn):
            self.store.append_event(second)
            self.store.append_event(first)

        events = self.store.list_events("run_1")
        self.assertEqual([event.id for event in events], ["evt_1", "evt_2"])
        self.assertEqual(events[0].payload, {"intent": "ask"})
        self.assertEqual(events[1].payload, {"allowed": True})

    def test_list_events_filters_by_run_id(self) -> None:
        insert_test_run_record(self.conn, "run_2")

        with SqliteUnitOfWork(self.conn):
            self.store.append_event(LogTraceEvent(run_id="run_1", seq=1, event_type="one", id="evt_1"))
            self.store.append_event(LogTraceEvent(run_id="run_2", seq=1, event_type="two", id="evt_2"))

        events = self.store.list_events("run_1")
        self.assertEqual([event.id for event in events], ["evt_1"])

    def test_append_event_requires_existing_run_record(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with SqliteUnitOfWork(self.conn):
                self.store.append_event(
                    LogTraceEvent(run_id="missing_run", seq=1, event_type="missing")
                )

    def test_append_event_surfaces_payload_serialization_errors(self) -> None:
        with self.assertRaises(SerializationError):
            with SqliteUnitOfWork(self.conn):
                self.store.append_event(
                    LogTraceEvent(
                        run_id="run_1",
                        seq=1,
                        event_type="bad.payload",
                        payload={"bad": object()},
                    )
                )


if __name__ == "__main__":
    unittest.main()
