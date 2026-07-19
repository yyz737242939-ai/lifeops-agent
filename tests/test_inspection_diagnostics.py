from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from app.inspection import (
    DiagnosticRegistry,
    InspectionQuery,
    InspectionTarget,
    InspectionView,
    InspectorService,
    default_diagnostic_registry,
)
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.runtime_reporting import (
    EmptyRuntimeFactProvider,
    FactProjection,
    RuntimeReportBuilder,
)
from app.runtime_reporting.annotations import AnnotationRunContext


class InspectionDiagnosticsTest(unittest.TestCase):
    def test_default_registry_freezes_ten_rules_and_is_deterministic(self) -> None:
        registry = default_diagnostic_registry()
        report = _flagged_report()
        context = AnnotationRunContext(created_at="2026-07-17T00:00:00+00:00")

        first = registry.evaluate(report, context)
        second = registry.evaluate(report, context)

        self.assertEqual(len(registry.rule_ids), 10)
        self.assertEqual(first, second)
        self.assertEqual(
            {annotation.reason_code for annotation in first.annotations},
            set(registry.rule_ids),
        )
        self.assertTrue(
            all(annotation.safe_explanation for annotation in first.annotations)
        )
        self.assertEqual(first.warnings, ())

    def test_registry_isolates_one_rule_failure(self) -> None:
        class BrokenRule:
            rule_id = "broken"

            def evaluate(self, report, context):
                raise RuntimeError("secret exception")

        healthy = default_diagnostic_registry().rules[0]
        result = DiagnosticRegistry((BrokenRule(), healthy)).evaluate(
            _flagged_report(),
            AnnotationRunContext(created_at="2026-07-17T00:00:00+00:00"),
        )

        self.assertEqual(result.warnings, ("diagnostic_rule_failed:broken",))
        self.assertTrue(result.annotations)

    def test_service_runs_diagnostics_only_for_diagnose_view(self) -> None:
        graph = _graph()

        class Reader:
            def find_by_run(self, run_id):
                return graph

        service = InspectorService(
            trace_reader=Reader(),
            fact_provider=EmptyRuntimeFactProvider(),
            report_builder=RuntimeReportBuilder(),
            diagnostic_registry=default_diagnostic_registry(),
            diagnostic_context=AnnotationRunContext(
                created_at="2026-07-17T00:00:00+00:00"
            ),
        )

        plain = service.inspect(InspectionQuery(InspectionTarget(run_id="run_diamond")))
        diagnosed = service.inspect(
            InspectionQuery(
                InspectionTarget(run_id="run_diamond"),
                views=(InspectionView.DIAGNOSE,),
            )
        )

        self.assertEqual(plain.diagnostic_annotations, ())
        self.assertEqual(
            {item.reason_code for item in diagnosed.diagnostic_annotations},
            {"first_failure", "downstream_blocked"},
        )

    def test_annotation_sink_failure_keeps_ephemeral_findings(self) -> None:
        graph = _graph()

        class Reader:
            def find_by_run(self, run_id):
                return graph

        class Sink:
            def __init__(self):
                self.calls = []

            def record(self, annotation):
                self.calls.append(annotation)
                raise OSError("secret sink failure")

        sink = Sink()
        service = InspectorService(
            trace_reader=Reader(),
            fact_provider=EmptyRuntimeFactProvider(),
            report_builder=RuntimeReportBuilder(),
            diagnostic_registry=default_diagnostic_registry(),
            diagnostic_context=AnnotationRunContext(
                created_at="2026-07-17T00:00:00+00:00"
            ),
            annotation_sink=sink,
        )

        result = service.inspect(
            InspectionQuery(
                InspectionTarget(run_id="run_diamond"),
                views=(InspectionView.DIAGNOSE,),
            )
        )

        self.assertEqual(len(sink.calls), 2)
        self.assertEqual(len(result.diagnostic_annotations), 2)
        self.assertTrue(
            all(item.startswith("annotation_not_persisted:") for item in result.warnings)
        )


def _flagged_report():
    graph = _graph()
    base = RuntimeReportBuilder().build(graph, EmptyRuntimeFactProvider().load(graph))
    return replace(
        base,
        plan_report=(
            FactProjection(
                "plan_step",
                "step_blocked",
                "blocked",
                {"lifeops.plan.step.outcome": "blocked"},
            ),
        ),
        executor_invocations=(
            FactProjection(
                "trace_span:EXECUTOR",
                "span_failed",
                "error",
                {
                    "lifeops.workflow.node.outcome": "failed",
                    "lifeops.executor.no_progress": True,
                },
            ),
        ),
        tool_attempts=(
            FactProjection(
                "trace_span:TOOL",
                "span_write",
                "ok",
                {
                    "lifeops.tool.outcome": "succeeded",
                    "lifeops.tool.effect": "write",
                    "lifeops.tool.evidence.count": 0,
                    "lifeops.tool.allowed": False,
                },
            ),
        ),
        final_answer_validation=FactProjection(
            "final_answer_validation", "validation_1", "failed"
        ),
        integrity_warnings=(
            "missing_parent",
            "source_conflict",
            "sensitive_data_exposed",
            "confirmation_boundary_violation",
        ),
    )


def _graph():
    return TraceReader(
        FileTraceStore(Path("tests/fixtures/traces/serial_diamond"))
    ).get_trace("trace_diamond")


if __name__ == "__main__":
    unittest.main()
