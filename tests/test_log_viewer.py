import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.log_viewer.server import list_sessions, load_session_log


class LogViewerTests(unittest.TestCase):
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

            with patch("app.log_viewer.server.CONVERSATION_DIR", log_dir):
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
