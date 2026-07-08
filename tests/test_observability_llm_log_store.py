from __future__ import annotations

import sqlite3
import unittest

from app.common.errors import SerializationError
from app.observability.events import LogLlmInteraction
from app.observability.llm_log_store import LogLlmInteractionStore
from app.storage.unit_of_work import SqliteUnitOfWork
from tests.helpers import create_test_connection, insert_test_run_record


class LogLlmInteractionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        insert_test_run_record(self.conn)
        self.store = LogLlmInteractionStore(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_log_llm_interaction_validates_required_fields(self) -> None:
        with self.assertRaises(ValueError):
            LogLlmInteraction(run_id="", seq=1, request={})
        with self.assertRaises(ValueError):
            LogLlmInteraction(run_id="run_1", seq=0, request={})
        with self.assertRaises(ValueError):
            LogLlmInteraction(run_id="run_1", seq=1, request="bad")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            LogLlmInteraction(run_id="run_1", seq=1, request={}, response="bad")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            LogLlmInteraction(run_id="run_1", seq=1, request={}, status="")

    def test_append_and_list_interactions_by_run_id_ordered_by_seq(self) -> None:
        second = LogLlmInteraction(
            run_id="run_1",
            seq=2,
            provider="openai",
            model="gpt-test",
            request={"messages": [{"role": "user", "content": "second"}]},
            response={"output_text": "two"},
            id="llm_2",
            created_at="2026-07-08T00:00:02+00:00",
        )
        first = LogLlmInteraction(
            run_id="run_1",
            seq=1,
            provider="openai",
            model="gpt-test",
            request={"messages": [{"role": "user", "content": "first"}]},
            response={"output_text": "one"},
            id="llm_1",
            created_at="2026-07-08T00:00:01+00:00",
        )

        with SqliteUnitOfWork(self.conn):
            self.store.append_interaction(second)
            self.store.append_interaction(first)

        interactions = self.store.list_interactions("run_1")
        self.assertEqual([interaction.id for interaction in interactions], ["llm_1", "llm_2"])
        self.assertEqual(interactions[0].request["messages"][0]["content"], "first")
        self.assertEqual(interactions[1].response, {"output_text": "two"})

    def test_list_interactions_filters_by_run_id(self) -> None:
        insert_test_run_record(self.conn, "run_2")

        with SqliteUnitOfWork(self.conn):
            self.store.append_interaction(
                LogLlmInteraction(run_id="run_1", seq=1, request={"input": "one"}, id="llm_1")
            )
            self.store.append_interaction(
                LogLlmInteraction(run_id="run_2", seq=1, request={"input": "two"}, id="llm_2")
            )

        interactions = self.store.list_interactions("run_1")
        self.assertEqual([interaction.id for interaction in interactions], ["llm_1"])

    def test_response_can_be_missing_for_failed_or_partial_interaction(self) -> None:
        with SqliteUnitOfWork(self.conn):
            self.store.append_interaction(
                LogLlmInteraction(
                    run_id="run_1",
                    seq=1,
                    request={"input": "hello"},
                    response=None,
                    status="error",
                    error_code="llm_request_failed",
                    id="llm_error",
                )
            )

        interaction = self.store.list_interactions("run_1")[0]
        self.assertIsNone(interaction.response)
        self.assertEqual(interaction.status, "error")
        self.assertEqual(interaction.error_code, "llm_request_failed")

    def test_append_interaction_requires_existing_run_record(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with SqliteUnitOfWork(self.conn):
                self.store.append_interaction(
                    LogLlmInteraction(run_id="missing_run", seq=1, request={})
                )

    def test_append_interaction_surfaces_request_serialization_errors(self) -> None:
        with self.assertRaises(SerializationError):
            with SqliteUnitOfWork(self.conn):
                self.store.append_interaction(
                    LogLlmInteraction(
                        run_id="run_1",
                        seq=1,
                        request={"bad": object()},
                    )
                )


if __name__ == "__main__":
    unittest.main()
