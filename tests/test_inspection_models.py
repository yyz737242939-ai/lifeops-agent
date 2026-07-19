from __future__ import annotations

import ast
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from app.inspection import (
    InspectionQuery,
    InspectionResult,
    InspectionTarget,
    InspectionView,
    InspectorValidationCode,
    InspectorValidationError,
)
from app.observability.trace_models import AnnotationRecord
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import (
    AnnotationKind,
    AnnotationProducer,
    AnnotationStatus,
)
from app.runtime_reporting import ReportIdentity, RuntimeReport


class InspectionModelsTest(unittest.TestCase):
    def test_target_requires_exactly_one_primary_identity(self) -> None:
        for values in ({}, {"trace_id": "trace_1", "run_id": "run_1"}):
            with self.subTest(values=values):
                with self.assertRaises(InspectorValidationError) as raised:
                    InspectionTarget(**values)
                self.assertEqual(
                    raised.exception.code,
                    InspectorValidationCode.TARGET_EXACTLY_ONE.value,
                )

        with self.assertRaises(InspectorValidationError) as raised:
            InspectionTarget(trace_id=" ")
        self.assertEqual(raised.exception.code, "inspection_invalid_field")

    def test_query_freezes_views_and_cross_field_validation(self) -> None:
        target = InspectionTarget(run_id="run_1", session_id="session_1")
        query = InspectionQuery(target)
        self.assertEqual(query.views, (InspectionView.SUMMARY,))
        with self.assertRaises(FrozenInstanceError):
            query.span_id = "span_1"  # type: ignore[misc]

        invalid_cases = (
            ({"views": ()}, InspectorValidationCode.VIEWS_REQUIRED),
            (
                {"views": (InspectionView.SUMMARY, InspectionView.SUMMARY)},
                InspectorValidationCode.DUPLICATE_VIEW,
            ),
            (
                {"span_id": "span_1"},
                InspectorValidationCode.SPAN_REQUIRES_DETAILS,
            ),
            (
                {"include_sensitive": True},
                InspectorValidationCode.SENSITIVE_REQUIRES_DETAILS,
            ),
        )
        for arguments, code in invalid_cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(InspectorValidationError) as raised:
                    InspectionQuery(target, **arguments)
                self.assertEqual(raised.exception.code, code.value)

        details = InspectionQuery(
            target,
            views=(InspectionView.DETAILS,),
            span_id="span_1",
            include_sensitive=True,
        )
        self.assertEqual(details.span_id, "span_1")

    def test_plan_span_query_is_rejected_as_ambiguous(self) -> None:
        with self.assertRaises(InspectorValidationError) as raised:
            InspectionQuery(
                InspectionTarget(plan_id="plan_1"),
                views=(InspectionView.DETAILS,),
                span_id="span_1",
            )
        self.assertEqual(
            raised.exception.code,
            InspectorValidationCode.SPAN_TARGET_AMBIGUOUS.value,
        )

    def test_result_reuses_shared_reports_and_annotations(self) -> None:
        target = InspectionTarget(trace_id="trace_1", session_id="session_1")
        report = _report("trace_1", "run_1", "session_1")
        annotation = AnnotationRecord(
            annotation_id="annotation_1",
            target_trace_id="trace_1",
            annotation_kind=AnnotationKind.DIAGNOSTIC,
            producer=AnnotationProducer.DETERMINISTIC_RULE,
            status=AnnotationStatus.WARNING,
        )

        result = InspectionResult(
            target=target,
            views=(InspectionView.SUMMARY, InspectionView.DIAGNOSE),
            trace_graphs=(_graph("trace_1", "run_1"),),
            runtime_reports=(report,),
            diagnostic_annotations=(annotation,),
            warnings=("index_unavailable",),
        )

        self.assertIs(result.runtime_reports[0], report)
        self.assertIs(result.diagnostic_annotations[0], annotation)

    def test_result_validation_is_stable(self) -> None:
        report = _report("trace_1", "run_1", "session_1")
        cases = (
            (
                InspectionTarget(run_id="run_1"),
                (),
                (),
                InspectorValidationCode.REPORTS_REQUIRED,
            ),
            (
                InspectionTarget(run_id="run_1"),
                (report, report),
                (),
                InspectorValidationCode.DUPLICATE_REPORT,
            ),
            (
                InspectionTarget(run_id="other_run"),
                (report,),
                (),
                InspectorValidationCode.TARGET_MISMATCH,
            ),
            (
                InspectionTarget(run_id="run_1"),
                (report,),
                (
                    AnnotationRecord(
                        annotation_id="annotation_2",
                        target_trace_id="other_trace",
                        annotation_kind=AnnotationKind.DIAGNOSTIC,
                        producer=AnnotationProducer.DETERMINISTIC_RULE,
                        status=AnnotationStatus.WARNING,
                    ),
                ),
                InspectorValidationCode.ANNOTATION_TARGET_MISMATCH,
            ),
        )
        for target, reports, annotations, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(InspectorValidationError) as raised:
                    InspectionResult(
                        target=target,
                        views=(InspectionView.SUMMARY,),
                        trace_graphs=(
                            _graph(reports[0].identity.trace_id, reports[0].identity.run_id),
                        ) if reports else (),
                        runtime_reports=reports,
                        diagnostic_annotations=annotations,
                    )
                self.assertEqual(raised.exception.code, code.value)

    def test_inspection_dependency_direction_is_read_only(self) -> None:
        allowed = (
            "app.inspection",
            "app.observability",
            "app.runtime_reporting",
        )
        inspection_imports = _app_imports(Path("app/inspection"))
        self.assertEqual(
            [name for name in inspection_imports if not name.startswith(allowed)],
            [],
        )
        self.assertNotIn("app.inspection", _app_imports(Path("app/observability")))


def _report(trace_id: str, run_id: str, session_id: str) -> RuntimeReport:
    return RuntimeReport(
        identity=ReportIdentity(trace_id, run_id, session_id, "turn_1"),
        route=None,
        intent_decision=None,
        policy_decision=None,
        selected_skills=(),
        context_report=None,
        plan_report=(),
        workflow_report=None,
        executor_invocations=(),
        tool_attempts=(),
        execution_feedback=None,
        recovery_report=None,
        evidence=(),
        final_answer_validation=None,
        stop_point=None,
        diagnostic_annotations=(),
        evaluation_annotations=(),
        integrity_warnings=(),
    )


def _graph(trace_id: str, run_id: str):
    graph = TraceReader(
        FileTraceStore(Path("tests/fixtures/traces/serial_diamond"))
    ).get_trace("trace_diamond")
    return replace(
        graph,
        trace=replace(graph.trace, trace_id=trace_id, run_id=run_id),
    )


def _app_imports(root: Path) -> list[str]:
    imports: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names if alias.name.startswith("app."))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("app."):
                    imports.append(node.module)
    return imports


if __name__ == "__main__":
    unittest.main()
