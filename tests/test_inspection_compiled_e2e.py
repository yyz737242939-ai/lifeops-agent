from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.inspection import (
    InspectionOutputFormat,
    InspectionQuery,
    InspectionRenderer,
    InspectionTarget,
    InspectionView,
    build_inspector_service,
    default_diagnostic_registry,
)
from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import (
    RequestTelemetry,
    SpanLinkInput,
    StartSpanInput,
    optional_span,
)
from app.observability.trace_index import TraceIndexBuilder
from app.observability.trace_models import AnnotationRecord, ArtifactReference
from app.observability.trace_vocabulary import (
    AnnotationKind,
    AnnotationProducer,
    AnnotationStatus,
    ArtifactSensitivity,
    LifeOpsSpanKind,
    SpanLinkType,
    TraceStatus,
)
from app.runtime_reporting import (
    EvidenceReport,
    FactProjection,
    RuntimeFactBundle,
)


class InspectorCompiledE2ETest(unittest.TestCase):
    def test_01_direct_final_only_summary_and_tree_have_zero_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_direct_final")
            telemetry = _telemetry(logs, "run_direct_final", "turn_1")
            with optional_span(
                telemetry,
                name="executor.invoke",
                kind=LifeOpsSpanKind.EXECUTOR,
            ):
                with optional_span(
                    telemetry,
                    name="executor.final",
                    kind=LifeOpsSpanKind.LLM,
                ):
                    pass
            telemetry.finish(status=TraceStatus.OK)

            result = _service(root).inspect(
                InspectionQuery(
                    InspectionTarget(run_id="run_direct_final"),
                    views=(InspectionView.SUMMARY, InspectionView.TREE),
                )
            )
            payload = _json(result)

            self.assertEqual(result.runtime_reports[0].tool_attempts, ())
            self.assertEqual(payload["sections"]["summary"][0]["tool_attempt_count"], 0)
            self.assertEqual(payload["sections"]["tree"][0][0]["kind"], "RUNTIME")

    def test_02_direct_tool_success_shows_guardrails_evidence_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_tool_success")
            telemetry = _telemetry(logs, "run_tool_success", "turn_1")
            with optional_span(
                telemetry,
                name="executor.invoke",
                kind=LifeOpsSpanKind.EXECUTOR,
            ):
                with optional_span(
                    telemetry,
                    name="tool.read",
                    kind=LifeOpsSpanKind.TOOL,
                    attributes={
                        "lifeops.tool.effect": "read",
                        "lifeops.tool.outcome": "succeeded",
                    },
                ):
                    with optional_span(
                        telemetry,
                        name="guardrail.pre",
                        kind=LifeOpsSpanKind.GUARDRAIL,
                    ):
                        pass
                    with optional_span(
                        telemetry,
                        name="guardrail.post",
                        kind=LifeOpsSpanKind.GUARDRAIL,
                    ):
                        pass
                    telemetry.add_artifact_reference(
                        ArtifactReference(
                            artifact_id="artifact_read_evidence",
                            trace_id=telemetry.trace_context.trace_id,
                            span_id=telemetry.trace_context.current_span_id,
                            artifact_type="tool_evidence",
                            storage_kind="fixture_reference",
                            safe_reference="fixture/evidence/read",
                            sensitivity=ArtifactSensitivity.INTERNAL,
                        )
                    )
            telemetry.finish(status=TraceStatus.OK)
            facts = RuntimeFactBundle(
                execution_feedback=FactProjection(
                    "execution_feedback", "feedback_1", "completed"
                ),
                final_answer_validation=FactProjection(
                    "final_answer_validation", "validation_1", "valid"
                ),
                evidence_reports=(
                    EvidenceReport(
                        "execution_feedback",
                        "evidence_1",
                        "fixture/evidence/read",
                    ),
                ),
            )
            result = _service(root, facts_by_run={"run_tool_success": facts}).inspect(
                InspectionQuery(
                    InspectionTarget(run_id="run_tool_success"),
                    views=(
                        InspectionView.SUMMARY,
                        InspectionView.TREE,
                        InspectionView.EVIDENCE,
                    ),
                )
            )
            payload = _json(result)

            tree_kinds = {item["kind"] for item in payload["sections"]["tree"][0]}
            self.assertIn("GUARDRAIL", tree_kinds)
            self.assertEqual(len(result.runtime_reports[0].evidence), 1)
            self.assertEqual(
                result.runtime_reports[0].final_answer_validation.status,
                "valid",
            )

    def test_03_direct_tool_failure_locates_first_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_tool_failure")
            telemetry = _telemetry(logs, "run_tool_failure", "turn_1")
            with optional_span(
                telemetry,
                name="executor.invoke",
                kind=LifeOpsSpanKind.EXECUTOR,
            ):
                with optional_span(
                    telemetry,
                    name="tool.failed",
                    kind=LifeOpsSpanKind.TOOL,
                    attributes={"lifeops.tool.outcome": "failed"},
                ) as scope:
                    scope.fail("fixture_tool_failed")
            telemetry.finish(status=TraceStatus.ERROR, error_code="fixture_tool_failed")

            result = _service(root, diagnose=True).inspect(
                InspectionQuery(
                    InspectionTarget(run_id="run_tool_failure"),
                    views=(InspectionView.DIAGNOSE,),
                )
            )

            finding = next(
                item
                for item in result.diagnostic_annotations
                if item.reason_code == "first_failure"
            )
            self.assertIsNotNone(finding.target_span_id)
            self.assertEqual(
                result.trace_graphs[0].spans_by_id[finding.target_span_id].name,
                "tool.failed",
            )

    def test_04_planning_preview_confirm_query_preserves_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_plan")
            preview = _telemetry(logs, "run_preview", "turn_preview")
            preview_trace_id = preview.trace_context.trace_id
            preview_root_id = preview.trace_context.current_span_id
            with optional_span(
                preview,
                name="planning.route",
                kind=LifeOpsSpanKind.PLANNER,
                attributes={"lifeops.plan.id": "plan_compiled"},
            ):
                pass
            preview.finish(status=TraceStatus.OK)

            confirm = _telemetry(logs, "run_confirm", "turn_confirm")
            confirm.add_link(
                SpanLinkInput(
                    target_trace_id=preview_trace_id,
                    target_span_id=preview_root_id,
                    link_type=SpanLinkType.PLAN_CONTINUATION,
                )
            )
            with optional_span(
                confirm,
                name="planning.confirm",
                kind=LifeOpsSpanKind.PLANNER,
                attributes={"lifeops.plan.id": "plan_compiled"},
            ):
                pass
            confirm.finish(status=TraceStatus.OK)

            result = _service(root).inspect(
                InspectionQuery(
                    InspectionTarget(plan_id="plan_compiled"),
                    views=(InspectionView.SUMMARY,),
                )
            )

            self.assertEqual(len(result.trace_graphs), 2)
            self.assertEqual(
                {report.identity.run_id for report in result.runtime_reports},
                {"run_preview", "run_confirm"},
            )
            self.assertTrue(
                any(
                    link.link_type is SpanLinkType.PLAN_CONTINUATION
                    for graph in result.trace_graphs
                    for link in graph.links
                )
            )

    def test_05_planning_partial_keeps_completed_failed_and_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_partial")
            telemetry = _telemetry(logs, "run_partial", "turn_1")
            for step_id, outcome, failed in (
                ("step_1", "completed", False),
                ("step_2", "failed", True),
                ("step_3", "not_run", False),
            ):
                with optional_span(
                    telemetry,
                    name=f"executor.{step_id}",
                    kind=LifeOpsSpanKind.EXECUTOR,
                    attributes={
                        "lifeops.plan.step.id": step_id,
                        "lifeops.plan.step.outcome": outcome,
                    },
                ) as scope:
                    if failed:
                        scope.fail("fixture_step_failed")
            telemetry.finish(status=TraceStatus.ERROR, error_code="fixture_step_failed")
            facts = RuntimeFactBundle(
                plan_runs_and_steps=tuple(
                    FactProjection(
                        "plan_step",
                        step_id,
                        outcome,
                        {"lifeops.plan.step.outcome": outcome},
                    )
                    for step_id, outcome in (
                        ("step_1", "completed"),
                        ("step_2", "failed"),
                        ("step_3", "not_run"),
                    )
                ),
                execution_feedback=FactProjection(
                    "execution_feedback", "feedback_partial", "partial"
                ),
            )
            result = _service(
                root,
                facts_by_run={"run_partial": facts},
                diagnose=True,
            ).inspect(
                InspectionQuery(
                    InspectionTarget(run_id="run_partial"),
                    views=(InspectionView.DIAGNOSE,),
                )
            )

            report = result.runtime_reports[0]
            self.assertEqual(
                [item.status for item in report.plan_report],
                ["completed", "failed", "not_run"],
            )
            self.assertEqual(report.execution_feedback.status, "partial")
            self.assertIn(
                "downstream_blocked",
                {item.reason_code for item in result.diagnostic_annotations},
            )

    def test_06_recovery_trace_has_recovery_link_and_zero_execution_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_recovery")
            telemetry = _telemetry(logs, "run_recovery", "turn_1")
            with optional_span(
                telemetry,
                name="recovery.explain",
                kind=LifeOpsSpanKind.RECOVERY,
            ):
                telemetry.add_link(
                    SpanLinkInput(
                        target_trace_id="trace_source",
                        link_type=SpanLinkType.RECOVERY_OF,
                    )
                )
            telemetry.finish(status=TraceStatus.OK)

            result = _service(root).inspect(
                InspectionQuery(InspectionTarget(run_id="run_recovery"))
            )
            graph = result.trace_graphs[0]

            self.assertTrue(
                any(link.link_type is SpanLinkType.RECOVERY_OF for link in graph.links)
            )
            self.assertFalse(
                any(
                    span.lifeops_span_kind
                    in {
                        LifeOpsSpanKind.TOOL,
                        LifeOpsSpanKind.POLICY,
                        LifeOpsSpanKind.EXECUTOR,
                        LifeOpsSpanKind.PLANNER,
                        LifeOpsSpanKind.GUARDRAIL,
                    }
                    for span in graph.spans_by_id.values()
                )
            )

    def test_07_eval_annotations_are_displayed_without_regrading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_eval")
            telemetry = _telemetry(logs, "run_eval", "turn_1")
            trace_id = telemetry.trace_context.trace_id
            telemetry.finish(status=TraceStatus.OK)
            logs.annotation_sink.record(
                AnnotationRecord(
                    annotation_id="annotation_eval_fixture",
                    target_trace_id=trace_id,
                    annotation_kind=AnnotationKind.EVALUATION,
                    producer=AnnotationProducer.DETERMINISTIC_RULE,
                    evaluator_id="fixture_grader",
                    eval_run_id="eval_run_1",
                    eval_suite_id="eval_suite_1",
                    eval_case_id="eval_case_1",
                    status=AnnotationStatus.PASSED,
                )
            )

            result = _service(root).inspect(
                InspectionQuery(
                    InspectionTarget(run_id="run_eval"),
                    views=(InspectionView.ANNOTATIONS,),
                )
            )
            payload = _json(result)

            self.assertEqual(len(result.runtime_reports[0].evaluation_annotations), 1)
            self.assertEqual(
                payload["sections"]["annotations"][0]["persisted_evaluation"][0]["status"],
                "passed",
            )
            self.assertEqual(result.diagnostic_annotations, ())

    def test_08_serial_diamond_tree_and_graph_keep_distinct_semantics(self) -> None:
        fixture = Path("tests/fixtures/traces/serial_diamond")
        result = _service(fixture).inspect(
            InspectionQuery(
                InspectionTarget(run_id="run_diamond"),
                views=(InspectionView.TREE, InspectionView.GRAPH),
            )
        )
        payload = _json(result)
        graph_rows = {
            item["node_id"]: item for item in payload["sections"]["graph"][0]
        }

        self.assertEqual(graph_rows["B"]["dependencies"], ["span_a"])
        self.assertEqual(graph_rows["C"]["outcome"], "failed")
        self.assertEqual(graph_rows["D"]["blocked_by"], ["span_c"])
        self.assertEqual(graph_rows["B"]["evidence"], ["artifact_b_evidence"])

    def test_09_index_delete_fallback_and_rebuild_preserve_report(self) -> None:
        fixture = Path("tests/fixtures/traces/serial_diamond")
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "trace-index.sqlite3"
            TraceIndexBuilder(index_path).index_session(fixture)
            query = InspectionQuery(InspectionTarget(run_id="run_diamond"))

            indexed = _service(fixture, index_path=index_path).inspect(query)
            index_path.unlink()
            fallback = _service(fixture, index_path=index_path).inspect(query)
            TraceIndexBuilder(index_path).index_session(fixture)
            rebuilt = _service(fixture, index_path=index_path).inspect(query)

            self.assertEqual(
                indexed.runtime_reports[0].executor_invocations,
                fallback.runtime_reports[0].executor_invocations,
            )
            self.assertEqual(
                indexed.runtime_reports[0].executor_invocations,
                rebuilt.runtime_reports[0].executor_invocations,
            )
            self.assertIn("index_unavailable", fallback.runtime_reports[0].integrity_warnings)
            self.assertNotIn("index_unavailable", rebuilt.runtime_reports[0].integrity_warnings)

    def test_10_corrupt_incomplete_sensitive_trace_degrades_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = SessionLogWriter.create(root, session_id="session_degraded")
            telemetry = _telemetry(logs, "run_degraded", "turn_1")
            telemetry.start_span(
                StartSpanInput(
                    "executor.incomplete",
                    LifeOpsSpanKind.EXECUTOR,
                    {"memory.content": "SECRET-CONTENT-MARKER", "safe.count": 1},
                )
            )
            telemetry.add_artifact_reference(
                ArtifactReference(
                    artifact_id="artifact_sensitive_fixture",
                    trace_id=telemetry.trace_context.trace_id,
                    span_id=telemetry.trace_context.current_span_id,
                    artifact_type="llm_interaction",
                    storage_kind="fixture_reference",
                    safe_reference="fixture/sensitive/interaction",
                    sensitivity=ArtifactSensitivity.SENSITIVE,
                )
            )
            telemetry.finish(status=TraceStatus.ERROR, error_code="fixture_incomplete")
            with logs.trace_exporter.path.open("a", encoding="utf-8") as handle:
                handle.write('{"record_type":"span"')

            result = _service(root).inspect(
                InspectionQuery(
                    InspectionTarget(run_id="run_degraded"),
                    views=(
                        InspectionView.DETAILS,
                        InspectionView.EVIDENCE,
                        InspectionView.INTEGRITY,
                    ),
                )
            )
            rendered = InspectionRenderer().render(
                result, InspectionOutputFormat.JSON
            )

            self.assertNotIn("SECRET-CONTENT-MARKER", rendered)
            self.assertIn("source_corrupt:", rendered)
            self.assertIn("trace_span_incomplete", rendered)
            self.assertIn('"content_included":false', rendered)


class _FactsByRun:
    def __init__(self, facts_by_run: dict[str, RuntimeFactBundle]) -> None:
        self._facts_by_run = facts_by_run

    def load(self, trace):
        return self._facts_by_run.get(trace.trace.run_id, RuntimeFactBundle())


def _service(
    root: Path,
    *,
    facts_by_run: dict[str, RuntimeFactBundle] | None = None,
    diagnose: bool = False,
    index_path: Path | None = None,
):
    return build_inspector_service(
        root,
        index_path=index_path,
        fact_provider=_FactsByRun(facts_by_run or {}),
        diagnostic_registry=default_diagnostic_registry() if diagnose else None,
    )


def _telemetry(logs: SessionLogWriter, run_id: str, turn_id: str) -> RequestTelemetry:
    metadata = json.loads(
        (logs.session_dir / "metadata.json").read_text(encoding="utf-8")
    )
    return RequestTelemetry(
        run_id=run_id,
        session_id=metadata["session_id"],
        turn_id=turn_id,
        legacy_sink=OptionalLogAppender(None),
        exporter=logs.trace_exporter,
        annotation_sink=logs.annotation_sink,
    )


def _json(result) -> dict[str, object]:
    return json.loads(
        InspectionRenderer().render(result, InspectionOutputFormat.JSON)
    )


if __name__ == "__main__":
    unittest.main()
