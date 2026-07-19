from __future__ import annotations

import unittest

from app.runtime_reporting.annotations import (
    AnnotationRunContext,
    TraceContractGrader,
    TraceIntegrityRule,
    persist_annotations,
)
from app.runtime_reporting.models import ReportIdentity, RuntimeReport


NOW = "2026-07-17T01:02:03+00:00"


class RuntimeReportAnnotationsTest(unittest.TestCase):
    def test_diagnostic_rule_is_deterministic_and_does_not_mutate_report(self) -> None:
        report = _report(("missing_parent:span_1:span_unknown",))
        before = report
        context = AnnotationRunContext(NOW)

        first = TraceIntegrityRule().evaluate(report, context)
        second = TraceIntegrityRule().evaluate(report, context)

        self.assertEqual(first, second)
        self.assertEqual(report, before)
        self.assertEqual(first[0].producer_version, "1")
        self.assertTrue(first[0].source_fingerprint)
        self.assertEqual(first[0].status.value, "warning")

    def test_grader_preserves_complete_eval_lineage_and_pass_fail(self) -> None:
        context = AnnotationRunContext(
            NOW, "eval_run_1", "suite_1", "case_1"
        )
        passed = TraceContractGrader().evaluate(_report(()), context)[0]
        failed = TraceContractGrader().evaluate(
            _report(("source_corrupt:file",)), context
        )[0]

        self.assertEqual(passed.status.value, "passed")
        self.assertEqual(passed.score, 1.0)
        self.assertEqual(failed.status.value, "failed")
        self.assertEqual(failed.score, 0.0)
        self.assertEqual(failed.eval_run_id, "eval_run_1")
        self.assertEqual(failed.eval_suite_id, "suite_1")
        self.assertEqual(failed.eval_case_id, "case_1")
        with self.assertRaises(ValueError):
            TraceContractGrader().evaluate(
                _report(()), AnnotationRunContext(NOW, eval_run_id="partial")
            )

    def test_annotation_sink_failure_is_isolated(self) -> None:
        annotation = TraceContractGrader().evaluate(
            _report(()),
            AnnotationRunContext(NOW, "eval_run_1", "suite_1", "case_1"),
        )[0]

        class FailingSink:
            def record(self, item):
                raise OSError("fixture failure")

        failed = persist_annotations(FailingSink(), (annotation,))
        self.assertEqual(failed, (annotation.annotation_id,))


def _report(warnings: tuple[str, ...]) -> RuntimeReport:
    return RuntimeReport(
        identity=ReportIdentity("trace_1", "run_1", "session_1", "turn_1"),
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
        integrity_warnings=warnings,
    )


if __name__ == "__main__":
    unittest.main()
