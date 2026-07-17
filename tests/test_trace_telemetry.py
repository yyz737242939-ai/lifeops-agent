from __future__ import annotations

import dataclasses
import tempfile
import unittest

from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import (
    EndSpanInput,
    RequestTelemetry,
    SpanEventInput,
    SpanLinkInput,
    StartSpanInput,
    TraceContext,
    optional_span,
)
from app.observability.trace_models import ArtifactReference, TraceRecord
from app.observability.trace_vocabulary import (
    ArtifactSensitivity,
    LifeOpsSpanKind,
    SpanLinkType,
    TraceStatus,
)


class TraceTelemetryTest(unittest.TestCase):
    def test_invalid_instrumentation_metadata_never_changes_business_flow(self) -> None:
        class CollectingExporter:
            def __init__(self) -> None:
                self.records = []

            def export(self, records) -> None:
                self.records.extend(records)

        exporter = CollectingExporter()
        telemetry = RequestTelemetry(
            run_id="run_safe",
            session_id="session_safe",
            turn_id="turn_safe",
            legacy_sink=OptionalLogAppender(None),
            exporter=exporter,
        )
        completed: list[str] = []

        with optional_span(
            telemetry,
            name="invalid.start",
            kind=LifeOpsSpanKind.CONTEXT,
            attributes={"raw_prompt": "fixture-redacted"},
        ) as scope:
            self.assertIsNone(scope.handle)
            completed.append("start")
        with optional_span(
            telemetry,
            name="invalid.end",
            kind=LifeOpsSpanKind.CONTEXT,
        ) as scope:
            scope.set_attributes({"tool.output": "fixture-redacted"})
            completed.append("end")

        telemetry.finish(status=TraceStatus.OK)

        self.assertEqual(completed, ["start", "end"])
        self.assertEqual(
            [record.status for record in exporter.records if isinstance(record, TraceRecord)],
            [TraceStatus.OK],
        )

    def test_trace_context_is_immutable_and_child_identity_is_request_local(self) -> None:
        telemetry, _logs, legacy = self._telemetry()
        root = telemetry.trace_context
        handle = telemetry.start_span(
            StartSpanInput("intent.classify", LifeOpsSpanKind.INTENT)
        )

        self.assertEqual(handle.context.trace_id, root.trace_id)
        self.assertEqual(handle.parent_span_id, root.current_span_id)
        self.assertNotEqual(handle.context.current_span_id, root.current_span_id)
        self.assertEqual(handle.context.run_id, "run_1")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            root.trace_id = "changed"  # type: ignore[misc]

        telemetry.end_span(EndSpanInput(handle))
        telemetry.finish(status=TraceStatus.OK)
        self.assertEqual(legacy, [])

    def test_records_event_link_artifact_and_append_compatibility(self) -> None:
        telemetry, logs, legacy = self._telemetry()
        with optional_span(
            telemetry, name="planner.route", kind=LifeOpsSpanKind.PLANNER,
            attributes={"lifeops.plan.id": "plan_1"},
        ):
            telemetry.append("planning.route.selected", {"route": "direct"})
            telemetry.add_event(SpanEventInput("planning.routed", attributes={"route": "direct"}))
            telemetry.add_link(
                SpanLinkInput("trace_preview", SpanLinkType.PLAN_CONTINUATION)
            )
            telemetry.add_artifact_reference(
                ArtifactReference(
                    artifact_id="artifact_1", trace_id=telemetry.trace_context.trace_id,
                    span_id=telemetry.trace_context.current_span_id,
                    artifact_type="execution_feedback", storage_kind="session_file",
                    safe_reference="artifacts/artifact_1.json",
                    sensitivity=ArtifactSensitivity.INTERNAL,
                )
            )
        telemetry.finish(status=TraceStatus.OK)

        rows = logs.trace_exporter.read_all()
        self.assertEqual(legacy, [("planning.route.selected", {"route": "direct"})])
        self.assertEqual(
            {row["record_type"] for row in rows},
            {"trace", "span", "span_event", "span_link", "artifact_reference"},
        )
        self.assertTrue(all(row["schema_version"] == 1 for row in rows))

    def test_old_append_only_fake_remains_compatible_with_optional_span(self) -> None:
        calls: list[tuple[str, dict[str, object] | None]] = []
        fake = OptionalLogAppender(lambda name, payload=None: calls.append((name, payload)))

        with optional_span(fake, name="runtime.test", kind=LifeOpsSpanKind.RUNTIME):
            fake.append("runtime.tested", {"status": "ok"})

        self.assertEqual(calls, [("runtime.tested", {"status": "ok"})])

    def test_trace_context_does_not_appear_in_graph_or_authorization_models(self) -> None:
        from app.orchestration.state import GraphState
        from app.runtime.models import RuntimeRequest
        from app.tools.models import ToolCall

        self.assertNotIn("trace_context", GraphState.__annotations__)
        self.assertNotIn("trace_context", RuntimeRequest.__annotations__)
        self.assertNotIn("trace_context", ToolCall.__annotations__)

    def test_export_failure_does_not_change_legacy_event_behavior(self) -> None:
        class FailingExporter:
            def export(self, records):
                raise OSError("fixture failure")

        calls: list[str] = []
        telemetry = RequestTelemetry(
            run_id="run_1", session_id="session_1", turn_id="turn_1",
            legacy_sink=OptionalLogAppender(lambda event, payload=None: calls.append(event)),
            exporter=FailingExporter(),
        )
        with self.assertLogs("lifeops.observability", level="ERROR"):
            telemetry.append("runtime.run.started")
            with optional_span(
                telemetry,
                name="intent.classify",
                kind=LifeOpsSpanKind.INTENT,
            ):
                pass
            telemetry.finish(status=TraceStatus.OK)
        self.assertEqual(calls, ["runtime.run.started"])

    def test_legacy_event_failure_does_not_prevent_trace_completion(self) -> None:
        class FailingLegacySink:
            def append(self, event_type, payload=None):
                raise OSError("fixture failure")

        telemetry = RequestTelemetry(
            run_id="run_1", session_id="session_1", turn_id="turn_1",
            legacy_sink=FailingLegacySink(),
        )
        with self.assertLogs("lifeops.observability", level="ERROR"):
            telemetry.append("runtime.run.started")
        telemetry.finish(status=TraceStatus.OK)

    def _telemetry(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        logs = SessionLogWriter.create(temp.name, session_id="session_1")
        legacy: list[tuple[str, dict[str, object] | None]] = []
        telemetry = RequestTelemetry(
            run_id="run_1", session_id="session_1", turn_id="turn_1",
            legacy_sink=OptionalLogAppender(
                lambda name, payload=None: legacy.append((name, payload))
            ),
            exporter=logs.trace_exporter, annotation_sink=logs.annotation_sink,
        )
        return telemetry, logs, legacy


if __name__ == "__main__":
    unittest.main()
