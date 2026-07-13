from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from app.observability.events import LogLlmInteraction, LogTraceEvent
from app.observability.file_logs import RequestLlmLog, SessionLogWriter
from app.runtime.models import RuntimeRequest
from app.observability.logger import OptionalLogAppender, configure_application_logging


class ObservabilityFileLogsTest(unittest.TestCase):
    def test_request_llm_log_assigns_ordered_request_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session = SessionLogWriter.create(tmpdir, session_id="session_llm")
            request = RuntimeRequest(
                user_input="hello",
                session_id="session_llm",
                run_id="run_llm",
                turn_id="turn_llm",
            )
            sink = RequestLlmLog(session.llm_log, request)

            sink.record(
                provider="openai-compatible",
                model="test-model",
                request={"input": "first"},
                response={"output": "one"},
            )
            sink.record(
                provider="openai-compatible",
                model="test-model",
                request={"input": "second"},
                response=None,
                status="failed",
                error_code="provider_failed",
            )

            rows = session.llm_log.read_all()
            self.assertEqual([row["seq"] for row in rows], [1, 2])
            self.assertEqual(rows[0]["run_id"], "run_llm")
            self.assertEqual(rows[0]["turn_id"], "turn_llm")
            self.assertEqual(rows[1]["status"], "failed")
            self.assertEqual(rows[1]["error_code"], "provider_failed")
    def test_optional_log_appender_ignores_missing_callback(self) -> None:
        appender = OptionalLogAppender(None)

        appender.append("runtime.intent.started")
        appender.append("runtime.intent.completed", {"intent_type": "chat"})

    def test_optional_log_appender_forwards_to_callback(self) -> None:
        calls: list[tuple[str, dict[str, object] | None]] = []

        def record(event_type: str, payload: dict[str, object] | None = None) -> None:
            calls.append((event_type, payload))

        appender = OptionalLogAppender(record)

        appender.append("runtime.intent.completed", {"intent_type": "chat"})

        self.assertEqual(
            calls,
            [("runtime.intent.completed", {"intent_type": "chat"})],
        )

    def test_session_log_writer_creates_metadata_and_jsonl_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SessionLogWriter.create(
                tmpdir,
                session_id="session_1",
                metadata={"purpose": "test"},
            )

            writer.append_event(
                LogTraceEvent(
                    run_id="run_1",
                    seq=1,
                    event_type="runtime.run.started",
                    session_id="session_1",
                    turn_id="turn_1",
                    payload={"ok": True},
                )
            )
            writer.append_llm(
                LogLlmInteraction(
                    run_id="run_1",
                    seq=1,
                    session_id="session_1",
                    turn_id="turn_1",
                    request={"messages": []},
                    response={"output": "hi"},
                )
            )

            self.assertTrue((writer.session_dir / "metadata.json").exists())
            events = writer.event_log.read_all()
            llm_rows = writer.llm_log.read_all()
            self.assertEqual(events[0]["event_type"], "runtime.run.started")
            self.assertEqual(events[0]["session_id"], "session_1")
            self.assertEqual(events[0]["payload"], {"ok": True})
            self.assertEqual(llm_rows[0]["request"], {"messages": []})
            self.assertEqual(llm_rows[0]["response"], {"output": "hi"})

    def test_application_logging_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)
            log_path = configure_application_logging(session_dir)
            configure_application_logging(session_dir)

            logger = logging.getLogger("lifeops")
            try:
                before = len(log_path.read_text(encoding="utf-8").splitlines()) if log_path.exists() else 0
                logger.info("hello from test")
                after_lines = log_path.read_text(encoding="utf-8").splitlines()

                self.assertEqual(len(after_lines), before + 1)
                self.assertIn("hello from test", after_lines[-1])
            finally:
                for handler in list(logger.handlers):
                    if (
                        isinstance(handler, logging.FileHandler)
                        and handler.baseFilename == str(log_path.resolve())
                    ):
                        logger.removeHandler(handler)
                        handler.close()

    def test_application_logging_switches_to_one_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_log = configure_application_logging(root / "session_a")
            second_log = configure_application_logging(root / "session_b")
            logger = logging.getLogger("lifeops")
            try:
                logger.warning("diagnostic-for-session-b")

                self.assertNotIn(
                    "diagnostic-for-session-b",
                    first_log.read_text(encoding="utf-8"),
                )
                self.assertIn(
                    "diagnostic-for-session-b",
                    second_log.read_text(encoding="utf-8"),
                )
                active = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.FileHandler)
                ]
                self.assertEqual(len(active), 1)
            finally:
                for handler in list(logger.handlers):
                    if isinstance(handler, logging.FileHandler) and Path(
                        handler.baseFilename
                    ).is_relative_to(root.resolve()):
                        logger.removeHandler(handler)
                        handler.close()


if __name__ == "__main__":
    unittest.main()
