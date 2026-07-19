from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry, optional_span
from app.observability.trace_index import TraceIndexBuilder
from app.observability.trace_models import AnnotationRecord, SpanRecord
from app.observability.trace_reader import FileTraceStore, TraceReadError, TraceReader
from app.observability.trace_vocabulary import (
    AnnotationKind,
    AnnotationProducer,
    AnnotationStatus,
    LifeOpsSpanKind,
    TraceStatus,
)


class TraceReaderTest(unittest.TestCase):
    def test_reconstructs_deterministic_graph_from_index_and_file_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs, trace_id = _write_trace(root)
            index_path = root / "index.sqlite3"
            TraceIndexBuilder(index_path).index_session(logs.session_dir)
            reader = TraceReader(FileTraceStore(root, index_path=index_path))

            indexed = reader.get_trace(trace_id)
            index_path.unlink()
            fallback = reader.get_trace(trace_id)

            self.assertEqual(indexed, fallback)
            self.assertEqual(indexed.trace.run_id, "run_1")
            self.assertEqual(indexed.root_span.lifeops_span_kind, LifeOpsSpanKind.RUNTIME)
            self.assertEqual(reader.find_by_run("run_1"), fallback)
            self.assertEqual(reader.find_by_plan("plan_1"), (fallback,))
            self.assertEqual(len(fallback.annotations), 1)

    def test_preview_trace_identity_is_resolved_from_canonical_span_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_preview")
            telemetry = RequestTelemetry(
                run_id="run_preview",
                session_id="session_preview",
                turn_id="turn_preview",
                legacy_sink=OptionalLogAppender(None),
                exporter=logs.trace_exporter,
            )
            trace_id = telemetry.trace_context.trace_id
            with optional_span(
                telemetry,
                name="planning.route",
                kind=LifeOpsSpanKind.PLANNER,
            ) as scope:
                scope.set_attributes({"lifeops.plan.id": "plan_preview"})
            telemetry.finish(status=TraceStatus.OK)

            store = FileTraceStore(root)
            self.assertEqual(
                store.find_plan_preview_trace_id("plan_preview"),
                trace_id,
            )
            index_path = root / "index.sqlite3"
            TraceIndexBuilder(index_path).index_session(logs.session_dir)
            self.assertEqual(
                FileTraceStore(
                    root,
                    index_path=index_path,
                ).find_plan_preview_trace_id("plan_preview"),
                trace_id,
            )

    def test_corrupt_tail_preserves_graph_and_reports_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs, trace_id = _write_trace(root)
            with logs.trace_exporter.path.open("a", encoding="utf-8") as handle:
                handle.write('{"record_type":"span"')

            graph = TraceReader(FileTraceStore(root)).get_trace(trace_id)

            self.assertTrue(
                any(
                    item.startswith("source_corrupt:")
                    for item in graph.integrity_warnings
                )
            )

    def test_stale_or_corrupt_index_falls_back_to_canonical_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs, trace_id = _write_trace(root)
            index_path = root / "index.sqlite3"
            TraceIndexBuilder(index_path).index_session(logs.session_dir)
            with logs.trace_exporter.path.open("a", encoding="utf-8") as handle:
                handle.write("\n")

            stale_fallback = TraceReader(
                FileTraceStore(root, index_path=index_path)
            ).get_trace(trace_id)
            self.assertEqual(stale_fallback.trace.trace_id, trace_id)

            index_path.write_bytes(b"not sqlite")
            corrupt_fallback = TraceReader(
                FileTraceStore(root, index_path=index_path)
            ).get_trace(trace_id)
            self.assertEqual(corrupt_fallback.trace.trace_id, trace_id)

    def test_missing_parent_isolated_as_warning_and_cycle_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs, trace_id = _write_trace(root)
            missing = SpanRecord(
                trace_id=trace_id, span_id="span_missing_parent",
                parent_span_id="span_unknown", name="orphan",
                lifeops_span_kind=LifeOpsSpanKind.EXECUTOR,
                started_at="2026-07-17T01:02:03+00:00",
            )
            _append_record(logs.trace_exporter.path, "span", asdict(missing))
            graph = TraceReader(FileTraceStore(root)).get_trace(trace_id)
            self.assertIn(
                "missing_parent:span_missing_parent:span_unknown",
                graph.integrity_warnings,
            )

            first = SpanRecord(
                trace_id=trace_id, span_id="span_cycle_a", parent_span_id="span_cycle_b",
                name="cycle.a", lifeops_span_kind=LifeOpsSpanKind.EXECUTOR,
                started_at="2026-07-17T01:02:03+00:00",
            )
            second = SpanRecord(
                trace_id=trace_id, span_id="span_cycle_b", parent_span_id="span_cycle_a",
                name="cycle.b", lifeops_span_kind=LifeOpsSpanKind.EXECUTOR,
                started_at="2026-07-17T01:02:03+00:00",
            )
            _append_record(logs.trace_exporter.path, "span", asdict(first))
            _append_record(logs.trace_exporter.path, "span", asdict(second))
            with self.assertRaises(TraceReadError):
                TraceReader(FileTraceStore(root)).get_trace(trace_id)

    def test_unknown_schema_and_conflicting_duplicate_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs, trace_id = _write_trace(root)
            rows = logs.trace_exporter.read_all()
            duplicate = next(row for row in rows if row["record_type"] == "span")
            duplicate["name"] = "conflicting.name"
            with logs.trace_exporter.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(duplicate) + "\n")
            with self.assertRaises(TraceReadError):
                TraceReader(FileTraceStore(root)).get_trace(trace_id)

            unknown = dict(rows[0])
            unknown["schema_version"] = 2
            logs.trace_exporter.path.write_text(json.dumps(unknown) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                TraceReader(FileTraceStore(root)).get_trace(trace_id)


def _write_trace(root: Path) -> tuple[SessionLogWriter, str]:
    logs = SessionLogWriter.create(root, session_id="session_1")
    telemetry = RequestTelemetry(
        run_id="run_1", session_id="session_1", turn_id="turn_1",
        legacy_sink=OptionalLogAppender(None), exporter=logs.trace_exporter,
        annotation_sink=logs.annotation_sink,
    )
    trace_id = telemetry.trace_context.trace_id
    with optional_span(
        telemetry, name="executor.invoke", kind=LifeOpsSpanKind.EXECUTOR,
        attributes={"lifeops.plan.id": "plan_1"},
    ):
        pass
    telemetry.record_annotation(
        AnnotationRecord(
            annotation_id="annotation_1", target_trace_id=trace_id,
            annotation_kind=AnnotationKind.DIAGNOSTIC,
            producer=AnnotationProducer.DETERMINISTIC_RULE,
            status=AnnotationStatus.INFORMATIONAL,
        )
    )
    telemetry.finish(status=TraceStatus.OK)
    return logs, trace_id


def _append_record(path: Path, record_type: str, entry: dict[str, object]) -> None:
    entry["record_type"] = record_type
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    unittest.main()
