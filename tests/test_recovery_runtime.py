from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    ExecutionFeedback,
    ExecutionPath,
    FeedbackOverallStatus,
    FinalAnswerValidation,
)
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.recovery.runtime import RecoveryRuntime
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from tests.helpers import insert_test_run_record


class RecoveryRuntimeTest(unittest.TestCase):
    def test_restart_reads_feedback_and_emits_only_runtime_recovery_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database = root / "lifeops.db"
            conn = connect_sqlite(database)
            try:
                migrate(conn)
                insert_test_run_record(conn, "run_source")
                SqliteExecutionFeedbackRepository(conn).save(_feedback())
            finally:
                conn.close()

            restarted = RecoveryRuntime(connect_sqlite(database), root / "logs")
            try:
                result = restarted.explain("session_1", "run_source")
            finally:
                restarted.close()

            rows = [
                json.loads(line)
                for path in (root / "logs").glob("session_*/traces.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result.context.source_run_id, "run_source")
        kinds = {
            row["lifeops_span_kind"]
            for row in rows
            if row["record_type"] == "span"
        }
        self.assertEqual(kinds, {"RUNTIME", "RECOVERY"})
        self.assertFalse(
            kinds.intersection({"TOOL", "POLICY", "GUARDRAIL", "EXECUTOR", "PLANNER"})
        )

    def test_runtime_module_has_no_execution_or_authorization_import(self) -> None:
        tree = ast.parse(Path("app/recovery/runtime.py").read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = (
            "app.executor",
            "app.policy",
            "app.planning",
            "app.tools",
            "app.runtime.service",
            "app.inspector",
            "app.eval",
        )
        self.assertEqual(
            [
                name
                for name in imports
                if any(name == item or name.startswith(item + ".") for item in forbidden)
            ],
            [],
        )

    def test_session_id_cannot_escape_log_root(self) -> None:
        conn = connect_sqlite(":memory:")
        migrate(conn)
        runtime = RecoveryRuntime(conn, "unused")
        try:
            with self.assertRaises(ValueError):
                runtime.explain("../other-session", "run_source")
        finally:
            runtime.close()


def _feedback() -> ExecutionFeedback:
    return ExecutionFeedback(
        "feedback_1",
        "trace_source",
        "run_source",
        "session_1",
        ExecutionPath.DIRECT,
        "Safe summarized goal",
        FeedbackOverallStatus.NOT_RUN,
        "not_run",
        None,
        (),
        (),
        (),
        "2026-07-17T00:00:00Z",
        validation=FinalAnswerValidation(
            ClaimStatus.VALID,
            AnswerOutputMode.MODEL,
        ),
    )


if __name__ == "__main__":
    unittest.main()
