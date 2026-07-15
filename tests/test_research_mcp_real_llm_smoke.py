from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.runtime.bootstrap import build_runtime_service
from app.runtime.models import RuntimeRequest, RuntimeStatus


@unittest.skipUnless(
    os.environ.get("LIFEOPS_RUN_REAL_LLM_RESEARCH_SMOKE") == "1",
    "Set LIFEOPS_RUN_REAL_LLM_RESEARCH_SMOKE=1 to call the configured LLM and Hugging Face.",
)
class ResearchMcpRealLlmSmokeTest(unittest.TestCase):
    def test_real_llm_runs_read_only_research_mcp_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database_path = root / "lifeops-smoke.db"
            log_root = root / "logs"
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "database": {"path": str(database_path)},
                        "logs": {"root": str(log_root)},
                        "skills": {"root": str(Path("app/skills").resolve())},
                    }
                ),
                encoding="utf-8",
            )
            request = RuntimeRequest(
                user_input=(
                    "Use the research skill and call research.search_papers exactly "
                    "once to search public Hugging Face papers for agent runtime. "
                    "This is one read-only lookup: do not create a plan and do not "
                    "save anything. Then answer with paper titles and canonical links."
                ),
                session_id="session_research_mcp_real_llm_smoke",
                run_id="run_research_mcp_real_llm_smoke",
                turn_id="turn_research_mcp_real_llm_smoke",
            )
            runtime = build_runtime_service(config_path)
            try:
                result = runtime.handle(request)
            finally:
                runtime.close()

            self.assertEqual(
                result.status,
                RuntimeStatus.OK,
                msg=f"status={result.status.value} error_code={result.error_code}",
            )
            self.assertIn("huggingface.co/papers/", result.message.lower())

            events_path = next(log_root.rglob("events.jsonl"))
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            completed_tools = [
                row
                for row in events
                if row["event_type"] == "tool.call.completed"
            ]
            requested_tools = [
                row
                for row in events
                if row["event_type"] == "tool.call.requested"
            ]
            failed_tools = [
                row
                for row in events
                if row["event_type"] == "tool.call.failed"
            ]
            self.assertEqual(len(requested_tools), 1)
            self.assertEqual(len(completed_tools), 1)
            self.assertEqual(failed_tools, [])
            self.assertEqual(
                completed_tools[0]["payload"]["tool_name"],
                "research.search_papers",
            )

            conn = sqlite3.connect(database_path)
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM research_sources"
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
