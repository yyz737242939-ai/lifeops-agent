import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.log_viewer.server import list_sessions, load_session_log


class LogViewerTests(unittest.TestCase):
    def test_lists_and_loads_three_channel_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_root = Path(temporary_directory)
            session_id = "session_20260623_120000_000001"
            session_dir = session_root / session_id
            session_dir.mkdir()
            (session_dir / "metadata.json").write_text(
                json.dumps(
                    {"session_id": session_id, "started_at": "2026-06-23T12:00:00"}
                ),
                encoding="utf-8",
            )
            (session_dir / "events.jsonl").write_text(
                '{"event":"run.started"}\n', encoding="utf-8"
            )
            (session_dir / "llm.jsonl").write_text("", encoding="utf-8")
            (session_dir / "application.log").write_text(
                "2026-06-23T12:00:00 | INFO | lifeops.application | started\n",
                encoding="utf-8",
            )

            with (
                patch("app.log_viewer.server.SESSION_DIR", session_root),
                patch("app.log_viewer.server.CONVERSATION_DIR", session_root / "old"),
            ):
                sessions = list_sessions()
                events = load_session_log(session_id, "events")
                application = load_session_log(session_id, "application")

        self.assertTrue(sessions[0]["has_events"])
        self.assertTrue(sessions[0]["has_llm"])
        self.assertTrue(sessions[0]["has_application"])
        self.assertEqual(events["events"][0]["event"], "run.started")
        self.assertEqual(application["events"][0]["level"], "INFO")

    def test_lists_and_loads_paired_session_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_dir = Path(temporary_directory)
            session_id = "session_20260622_120000_000001"
            trace = {
                "session_id": session_id,
                "started_at": "2026-06-22T12:00:00",
                "kind": "structured_trace",
                "events": [{"event": "skill_routing"}],
            }
            raw = {
                "session_id": session_id,
                "started_at": "2026-06-22T12:00:00",
                "kind": "raw_llm_io",
                "events": [],
            }
            (log_dir / f"{session_id}_trace.json").write_text(
                json.dumps(trace), encoding="utf-8"
            )
            (log_dir / f"{session_id}_raw.json").write_text(
                json.dumps(raw), encoding="utf-8"
            )

            with (
                patch("app.log_viewer.server.CONVERSATION_DIR", log_dir),
                patch("app.log_viewer.server.SESSION_DIR", log_dir / "new"),
            ):
                sessions = list_sessions()
                loaded = load_session_log(session_id, "trace")

        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["has_trace"])
        self.assertTrue(sessions[0]["has_raw"])
        self.assertEqual(loaded["events"][0]["event"], "skill_routing")

    def test_rejects_invalid_session_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid session id"):
            load_session_log("../secrets", "trace")

    def test_rejects_invalid_log_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid log kind"):
            load_session_log("session_20260622_120000_000001", "other")


if __name__ == "__main__":
    unittest.main()
