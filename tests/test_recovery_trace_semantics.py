from __future__ import annotations

import tempfile
import unittest

from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.recovery_trace import (
    record_execution_feedback_reference,
    record_recovery_context_reference,
    record_recovery_of,
)
from app.observability.telemetry import RequestTelemetry, optional_span
from app.observability.trace_vocabulary import LifeOpsSpanKind, TraceStatus


class RecoveryTraceSemanticsTest(unittest.TestCase):
    def test_finalized_feedback_reference_projects_without_feedback_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = SessionLogWriter.create(tmpdir, session_id="session_1")
            telemetry = RequestTelemetry(
                run_id="run_1", session_id="session_1", turn_id="turn_1",
                legacy_sink=OptionalLogAppender(None), exporter=logs.trace_exporter,
            )
            artifact = record_execution_feedback_reference(
                telemetry,
                safe_reference="feedback/run_1",
                content_hash="a" * 64,
            )
            telemetry.finish(status=TraceStatus.OK)

            self.assertIsNotNone(artifact)
            rows = logs.trace_exporter.read_all()
            projected = next(row for row in rows if row["record_type"] == "artifact_reference")
            self.assertEqual(projected["artifact_type"], "execution_feedback")
            self.assertNotIn("actions", projected)
            self.assertNotIn("evidence", projected)

    def test_recovery_trace_links_to_source_and_contains_no_execution_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = SessionLogWriter.create(tmpdir, session_id="session_1")
            telemetry = RequestTelemetry(
                run_id="recovery_run_1", session_id="session_1", turn_id="turn_2",
                legacy_sink=OptionalLogAppender(None), exporter=logs.trace_exporter,
            )
            with optional_span(
                telemetry, name="recovery.explain", kind=LifeOpsSpanKind.RECOVERY
            ):
                record_recovery_context_reference(
                    telemetry, safe_reference="recovery-context/run_source"
                )
                record_recovery_of(
                    telemetry,
                    source_trace_id="trace_source",
                    source_span_id="span_source",
                )
            telemetry.finish(status=TraceStatus.OK)

            rows = logs.trace_exporter.read_all()
            link = next(row for row in rows if row["record_type"] == "span_link")
            self.assertEqual(link["link_type"], "recovery_of")
            self.assertEqual(link["target_trace_id"], "trace_source")
            kinds = {
                row["lifeops_span_kind"]
                for row in rows
                if row["record_type"] == "span"
            }
            self.assertEqual(kinds, {"RUNTIME", "RECOVERY"})
            self.assertTrue(
                kinds.isdisjoint({"TOOL", "POLICY", "EXECUTOR", "PLANNER", "GUARDRAIL"})
            )
            context = next(
                row
                for row in rows
                if row["record_type"] == "artifact_reference"
            )
            self.assertEqual(context["artifact_type"], "recovery_context")
            self.assertNotIn("goal", context)
            self.assertNotIn("evidence", context)

    def test_append_only_fake_keeps_feedback_and_recovery_projection_optional(self) -> None:
        fake = OptionalLogAppender(None)
        self.assertIsNone(
            record_execution_feedback_reference(fake, safe_reference="feedback/run_1")
        )
        record_recovery_of(fake, source_trace_id="trace_source")

    def test_projection_recorder_failure_is_non_intrusive(self) -> None:
        exploding = _ExplodingRecorder()
        self.assertIsNone(
            record_execution_feedback_reference(
                exploding, safe_reference="feedback/run_1"
            )
        )
        self.assertIsNone(
            record_recovery_context_reference(
                exploding, safe_reference="recovery-context/run_1"
            )
        )
        record_recovery_of(exploding, source_trace_id="trace_source")


class _ExplodingRecorder:
    @property
    def trace_context(self):
        class Context:
            trace_id = "trace_1"
            current_span_id = "span_1"

        return Context()

    def add_artifact_reference(self, _artifact) -> None:
        raise RuntimeError("export failed with sensitive diagnostic")

    def add_link(self, _link) -> None:
        raise RuntimeError("export failed with sensitive diagnostic")


if __name__ == "__main__":
    unittest.main()
