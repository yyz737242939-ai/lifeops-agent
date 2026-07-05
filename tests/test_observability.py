import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.observability import app_log, close_logging_session, events, llm_io
from app.observability.session import start_logging_session
from app.runtime.interaction_state import PendingConfirmation, RiskLevel


class FakeSDKResponse:
    output_text = "hi"

    def model_dump(self, **_kwargs) -> dict:
        return {
            "id": "response-test",
            "model": "test-model",
            "status": "completed",
            "output": [{"type": "message", "text": "hi"}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "instructions": "duplicated system instructions",
            "tools": [{"name": "duplicated_tool_schema"}],
            "temperature": 0,
            "error": None,
            "incomplete_details": None,
        }


class ObservabilityTests(unittest.TestCase):
    def test_writes_three_separate_log_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch("app.observability.session.LOG_ROOT", root):
                files = start_logging_session()
                run_state = SimpleNamespace(
                    run_id="run-test",
                    chat_llm_request_count=1,
                    to_dict=lambda **_kwargs: {"run_id": "run-test"},
                )

                events.log_run_started(run_state, {"max_llm_rounds": 2})
                events.log_llm_requested(run_state, 1, {"message_count": 1})
                llm_io.log_request(
                    run_state,
                    1,
                    1,
                    model="test-model",
                    instructions="system",
                    tools=[],
                    input_messages=[{"role": "user", "content": "hello"}],
                    parameters={"temperature": 0},
                )
                llm_io.log_response(
                    run_state,
                    1,
                    FakeSDKResponse(),
                )
                events.log_run_completed(run_state)
                app_log.log_info("Run %s completed", run_state.run_id)

                event_records = self._read_jsonl(files["events"])
                llm_records = self._read_jsonl(files["llm"])
                application_text = files["application"].read_text(encoding="utf-8")
                close_logging_session()

        self.assertEqual(event_records[0]["event"], "run.started")
        self.assertEqual(event_records[0]["run_id"], "run-test")
        self.assertEqual(
            [record["event"] for record in event_records],
            ["run.started", "llm.requested", "run.completed"],
        )
        self.assertEqual(
            [record["event"] for record in llm_records],
            ["llm.request", "llm.response"],
        )
        self.assertEqual(llm_records[0]["chat_llm_round_number"], 1)
        self.assertEqual(llm_records[0]["chat_llm_request_number"], 1)
        self.assertNotIn("loop", llm_records[0])
        self.assertNotIn("attempt", llm_records[0])
        response_record = llm_records[1]
        self.assertEqual(
            response_record["response_log_format"],
            "diagnostic_projection_v1",
        )
        self.assertEqual(response_record["response"]["output_text"], "hi")
        self.assertEqual(response_record["response"]["status"], "completed")
        self.assertIn("output", response_record["response"])
        self.assertIn("usage", response_record["response"])
        self.assertNotIn("instructions", response_record["response"])
        self.assertNotIn("tools", response_record["response"])
        self.assertNotIn("temperature", response_record["response"])
        self.assertNotIn("error", response_record["response"])
        self.assertNotIn("incomplete_details", response_record["response"])
        self.assertNotIn("tool.result", json.dumps(llm_records))
        self.assertIn("INFO", application_text)
        self.assertIn("run-test", application_text)

    def test_interaction_pending_event_uses_compact_diagnostic_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch("app.observability.session.LOG_ROOT", root):
                files = start_logging_session()
                run_state = SimpleNamespace(run_id="run-test")
                pending = PendingConfirmation(
                    id="pending-test",
                    operation="delete_all_memories",
                    tool_name="delete_memory",
                    risk_level=RiskLevel.HIGH,
                    scope_summary="delete all active memories",
                    arguments={"scope": "all_active"},
                    source_user_input="删除所有记忆。",
                )

                events.log_interaction_pending(
                    run_state,
                    "created",
                    pending,
                    current_turn_index=1,
                    reason="bulk_memory_delete",
                )

                event_records = self._read_jsonl(files["events"])
                close_logging_session()

        record = event_records[0]
        self.assertEqual(record["event"], "interaction.pending.created")
        self.assertEqual(record["pending_id"], "pending-test")
        self.assertEqual(record["operation"], "delete_all_memories")
        self.assertEqual(record["tool_name"], "delete_memory")
        self.assertEqual(record["risk_level"], "high")
        self.assertEqual(record["scope_summary"], "delete all active memories")
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["current_turn_index"], 1)
        self.assertEqual(record["reason"], "bulk_memory_delete")
        self.assertNotIn("source_user_input", record)
        self.assertNotIn("arguments", record)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
