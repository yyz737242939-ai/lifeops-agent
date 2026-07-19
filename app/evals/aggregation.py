"""Deterministic required/optional case and suite aggregation."""

from __future__ import annotations

from dataclasses import replace

from app.evals.contracts import (
    CaseResult,
    CaseStatus,
    EvalCounts,
    EvalReport,
    EvalRun,
    EvalRunStatus,
    FailureClassification,
    GradeResult,
    GradeStatus,
)
from app.evals.models import EvalCase


def aggregate_case_result(
    case: EvalCase,
    *,
    eval_run_id: str,
    suite_id: str,
    grade_results: tuple[GradeResult, ...],
    duration_ms: int,
    target_trace_id: str | None = None,
    evaluator_trace_id: str | None = None,
    warnings: tuple[str, ...] = (),
) -> CaseResult:
    if not isinstance(case, EvalCase):
        raise ValueError("case must be EvalCase.")
    if not isinstance(grade_results, tuple) or not all(
        isinstance(item, GradeResult) for item in grade_results
    ):
        raise ValueError("grade_results must contain only GradeResult values.")
    required = tuple(item for item in grade_results if item.required)
    optional = tuple(item for item in grade_results if not item.required)
    live = "live" in case.tags or "real-llm" in case.tags
    classification = None
    if not required:
        status = CaseStatus.ERROR
        classification = FailureClassification.HARNESS_ERROR
    elif any(item.status is GradeStatus.ERROR for item in required):
        status = CaseStatus.ERROR
        classification = FailureClassification.HARNESS_ERROR
    elif any(item.status is GradeStatus.UNAVAILABLE for item in required):
        if live:
            status = CaseStatus.UNAVAILABLE
            classification = FailureClassification.ENVIRONMENT_UNAVAILABLE
        else:
            status = CaseStatus.ERROR
            classification = FailureClassification.HARNESS_ERROR
    elif any(item.status is GradeStatus.SKIPPED for item in required):
        status = CaseStatus.ERROR
        classification = FailureClassification.HARNESS_ERROR
    elif any(item.status is GradeStatus.FAILED for item in required):
        status = CaseStatus.FAILED
        classification = FailureClassification.PRODUCT_FAILURE
    else:
        status = CaseStatus.PASSED
    optional_warnings = tuple(
        item.reason_code
        for item in optional
        if item.status
        in (
            GradeStatus.FAILED,
            GradeStatus.WARNING,
            GradeStatus.UNAVAILABLE,
            GradeStatus.ERROR,
        )
    )
    return CaseResult(
        eval_run_id=eval_run_id,
        suite_id=suite_id,
        case_id=case.case_id,
        status=status,
        grade_results=grade_results,
        duration_ms=duration_ms,
        required=case.required,
        target_trace_id=target_trace_id,
        evaluator_trace_id=evaluator_trace_id,
        failure_classification=classification,
        warnings=tuple(dict.fromkeys((*warnings, *optional_warnings))),
    )


def aggregate_eval_report(
    run: EvalRun,
    case_results: tuple[CaseResult, ...],
    *,
    ended_at: str,
    warnings: tuple[str, ...] = (),
) -> EvalReport:
    if not isinstance(run, EvalRun):
        raise ValueError("run must be EvalRun.")
    if not isinstance(case_results, tuple) or not all(
        isinstance(item, CaseResult) for item in case_results
    ):
        raise ValueError("case_results must contain only CaseResult values.")
    if any(
        item.eval_run_id != run.eval_run_id or item.suite_id != run.suite_id
        for item in case_results
    ):
        raise ValueError("case results must match the eval run identity.")
    counts = EvalCounts(
        passed=sum(item.status is CaseStatus.PASSED for item in case_results),
        failed=sum(item.status is CaseStatus.FAILED for item in case_results),
        skipped=sum(item.status is CaseStatus.SKIPPED for item in case_results),
        unavailable=sum(item.status is CaseStatus.UNAVAILABLE for item in case_results),
        error=sum(item.status is CaseStatus.ERROR for item in case_results),
    )
    required = tuple(item for item in case_results if item.required)
    status = (
        EvalRunStatus.ERROR
        if any(item.status in (CaseStatus.ERROR, CaseStatus.SKIPPED) for item in required)
        else EvalRunStatus.FAILED
        if any(item.status is CaseStatus.FAILED for item in required)
        else EvalRunStatus.UNAVAILABLE
        if any(item.status is CaseStatus.UNAVAILABLE for item in required)
        else EvalRunStatus.PASSED
    )
    completed_run = replace(run, status=status, ended_at=ended_at)
    return EvalReport(
        run=completed_run,
        case_results=case_results,
        counts=counts,
        warnings=warnings,
    )


def eval_exit_code(report: EvalReport) -> int:
    if not isinstance(report, EvalReport):
        raise ValueError("report must be EvalReport.")
    return {
        EvalRunStatus.PASSED: 0,
        EvalRunStatus.FAILED: 1,
        EvalRunStatus.ERROR: 2,
        EvalRunStatus.UNAVAILABLE: 3,
    }.get(report.run.status, 2)
