from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry, optional_span
from app.observability.trace_index import TraceIndexBuilder
from app.observability.trace_vocabulary import LifeOpsSpanKind, TraceStatus


class TraceIndexBuilderTest(unittest.TestCase):
    def test_indexes_rebuilds_and_can_be_deleted_without_touching_canonical_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = _write_trace(root)
            index_path = root / "index" / "lifeops_trace_index.sqlite3"
            builder = TraceIndexBuilder(index_path)

            first = builder.index_session(logs.session_dir)
            second = builder.index_session(logs.session_dir)

            self.assertEqual(first.indexed_records, second.indexed_records)
            conn = sqlite3.connect(index_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0], 1)
                self.assertGreater(conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0], 1)
                self.assertEqual(
                    conn.execute(
                        "SELECT plan_id FROM spans WHERE plan_id IS NOT NULL"
                    ).fetchone()[0],
                    "plan_1",
                )
            finally:
                conn.close()
            canonical = logs.trace_exporter.path.read_text(encoding="utf-8")
            index_path.unlink()
            self.assertEqual(logs.trace_exporter.path.read_text(encoding="utf-8"), canonical)
            rebuilt = builder.index_session(logs.session_dir)
            self.assertEqual(rebuilt.indexed_records, first.indexed_records)

    def test_corrupt_tail_keeps_prior_records_and_marks_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = _write_trace(root)
            with logs.trace_exporter.path.open("a", encoding="utf-8") as handle:
                handle.write('{"record_type":"span"')

            report = TraceIndexBuilder(root / "index.sqlite3").index_session(
                logs.session_dir
            )

            self.assertEqual(len(report.corrupt_files), 1)
            self.assertGreater(report.indexed_records, 0)

    def test_index_schema_is_separate_from_runtime_storage(self) -> None:
        source = Path("app/observability/trace_index.py").read_text(encoding="utf-8")
        self.assertNotIn("app.storage", source)
        self.assertNotIn("tool_calls", source)
        self.assertNotIn("run_records", source)


def _write_trace(root: Path) -> SessionLogWriter:
    logs = SessionLogWriter.create(root, session_id="session_1")
    telemetry = RequestTelemetry(
        run_id="run_1", session_id="session_1", turn_id="turn_1",
        legacy_sink=OptionalLogAppender(None), exporter=logs.trace_exporter,
        annotation_sink=logs.annotation_sink,
    )
    with optional_span(
        telemetry,
        name="executor.invoke_plan_step",
        kind=LifeOpsSpanKind.EXECUTOR,
        attributes={"lifeops.plan.id": "plan_1"},
    ):
        pass
    telemetry.finish(status=TraceStatus.OK)
    return logs


if __name__ == "__main__":
    unittest.main()
