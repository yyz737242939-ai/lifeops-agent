from __future__ import annotations

import json
import unittest

from app.evals import (
    EVAL_MANIFEST_SCHEMA_VERSION,
    CaseStatus,
    EvalCase,
    EvalExecutionMode,
    EvalExpectations,
    EvalOutputFormat,
    EvalReportRenderer,
    EvalRun,
    EvalRunStatus,
    FailureClassification,
    GradeResult,
    GradeStatus,
    aggregate_case_result,
    aggregate_eval_report,
    eval_exit_code,
)


class EvalAggregationRendererTest(unittest.TestCase):
    def test_required_and_optional_grades_keep_failure_classes_separate(self) -> None:
        offline = _case("offline-case")
        live = _case("live-case", tags=("live",))
        cases = (
            (
                offline,
                (_grade("tool-call", GradeStatus.FAILED),),
                CaseStatus.FAILED,
                FailureClassification.PRODUCT_FAILURE,
            ),
            (
                offline,
                (_grade("tool-call", GradeStatus.ERROR),),
                CaseStatus.ERROR,
                FailureClassification.HARNESS_ERROR,
            ),
            (
                live,
                (_grade("tool-call", GradeStatus.UNAVAILABLE),),
                CaseStatus.UNAVAILABLE,
                FailureClassification.ENVIRONMENT_UNAVAILABLE,
            ),
            (
                offline,
                (
                    _grade("trace-contract", GradeStatus.PASSED),
                    _grade("privacy", GradeStatus.FAILED, required=False),
                ),
                CaseStatus.PASSED,
                None,
            ),
        )
        for case, grades, status, classification in cases:
            with self.subTest(case=case.case_id, status=status):
                result = aggregate_case_result(
                    case,
                    eval_run_id="eval-1",
                    suite_id="runtime-core",
                    grade_results=grades,
                    duration_ms=5,
                    target_trace_id="trace-1",
                )
                self.assertEqual(result.status, status)
                self.assertEqual(result.failure_classification, classification)
                if not grades[-1].required:
                    self.assertEqual(result.warnings, (grades[-1].reason_code,))

    def test_suite_status_counts_and_exit_codes_follow_frozen_contract(self) -> None:
        run = _run()
        status_codes = (
            (CaseStatus.PASSED, EvalRunStatus.PASSED, 0),
            (CaseStatus.FAILED, EvalRunStatus.FAILED, 1),
            (CaseStatus.ERROR, EvalRunStatus.ERROR, 2),
            (CaseStatus.UNAVAILABLE, EvalRunStatus.UNAVAILABLE, 3),
        )
        for case_status, run_status, code in status_codes:
            with self.subTest(case_status=case_status):
                case_result = _case_result(case_status)
                report = aggregate_eval_report(
                    run,
                    (case_result,),
                    ended_at="2026-07-19T02:00:00+00:00",
                )
                self.assertEqual(report.run.status, run_status)
                self.assertEqual(eval_exit_code(report), code)
                self.assertEqual(
                    getattr(report.counts, case_status.value),
                    1,
                )

        skipped = aggregate_eval_report(
            run,
            (_case_result(CaseStatus.SKIPPED),),
            ended_at="2026-07-19T02:00:00+00:00",
        )
        self.assertEqual(skipped.run.status, EvalRunStatus.ERROR)
        self.assertEqual(eval_exit_code(skipped), 2)

    def test_text_and_json_reports_show_safe_failure_diagnostics(self) -> None:
        failed_case = aggregate_case_result(
            _case("failed-case"),
            eval_run_id="eval-1",
            suite_id="runtime-core",
            grade_results=(_grade("tool-call", GradeStatus.FAILED),),
            duration_ms=7,
            target_trace_id="trace-1",
        )
        report = aggregate_eval_report(
            _run(),
            (failed_case,),
            ended_at="2026-07-19T02:00:00+00:00",
        )
        renderer = EvalReportRenderer()

        text = renderer.render(report)
        payload = json.loads(renderer.render(report, EvalOutputFormat.JSON))

        self.assertIn("suite=runtime-core", text)
        self.assertIn("reason=tool-call_reason", text)
        self.assertEqual(payload["run"]["environment_fingerprint"], "offline-fixture-v1")
        self.assertEqual(payload["cases"][0]["inspector_identity"], {"trace_id": "trace-1"})
        grade = payload["cases"][0]["failed_grades"][0]
        self.assertEqual(grade["safe_expected"], {"count": 0})
        self.assertEqual(grade["safe_actual"], {"count": 1})


def _case(case_id: str, *, tags: tuple[str, ...] = ()) -> EvalCase:
    return EvalCase(
        schema_version=EVAL_MANIFEST_SCHEMA_VERSION,
        case_id=case_id,
        title="Case",
        description="Aggregation case.",
        execution_mode=EvalExecutionMode.RUNTIME_REQUEST,
        input={},
        expectations=EvalExpectations(),
        grader_ids=("trace-contract",),
        tags=tags,
    )


def _grade(
    grader_id: str,
    status: GradeStatus,
    *,
    required: bool = True,
) -> GradeResult:
    return GradeResult(
        grade_id=f"grade.{grader_id}",
        grader_id=grader_id,
        grader_version="1.0.0",
        status=status,
        reason_code=f"{grader_id}_reason",
        safe_explanation="Safe deterministic explanation.",
        required=required,
        target_trace_id="trace-1",
        fact_references=("fact-1",),
        safe_expected={"count": 0},
        safe_actual={"count": 1},
    )


def _run() -> EvalRun:
    return EvalRun(
        eval_run_id="eval-1",
        suite_id="runtime-core",
        suite_version="1.0.0",
        environment_fingerprint="offline-fixture-v1",
        started_at="2026-07-19T01:00:00+00:00",
    )


def _case_result(status: CaseStatus):
    classification = {
        CaseStatus.FAILED: FailureClassification.PRODUCT_FAILURE,
        CaseStatus.ERROR: FailureClassification.HARNESS_ERROR,
        CaseStatus.UNAVAILABLE: FailureClassification.ENVIRONMENT_UNAVAILABLE,
    }.get(status)
    from app.evals import CaseResult

    return CaseResult(
        eval_run_id="eval-1",
        suite_id="runtime-core",
        case_id=f"case-{status.value}",
        status=status,
        grade_results=(_grade("trace-contract", GradeStatus.PASSED),),
        duration_ms=1,
        failure_classification=classification,
    )


if __name__ == "__main__":
    unittest.main()
