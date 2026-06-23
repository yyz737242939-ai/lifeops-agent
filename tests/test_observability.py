import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.observability import app_log, close_logging_session, events, llm_io
from app.observability.session import start_logging_session


class ObservabilityTests(unittest.TestCase):
    def test_writes_three_separate_log_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch("app.observability.session.LOG_ROOT", root):
                files = start_logging_session()
                run_state = SimpleNamespace(
                    run_id="run-test",
                    llm_attempts=1,
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
                    SimpleNamespace(output_text="hi", output=[]),
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
        self.assertNotIn("tool.result", json.dumps(llm_records))
        self.assertIn("INFO", application_text)
        self.assertIn("run-test", application_text)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
