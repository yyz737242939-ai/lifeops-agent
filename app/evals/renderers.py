"""Deterministic safe text and JSON rendering for EvalReport."""

from __future__ import annotations

import json
from enum import StrEnum

from app.evals.contracts import EvalReport, GradeStatus


class EvalOutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class EvalReportRenderer:
    def render(
        self,
        report: EvalReport,
        output_format: EvalOutputFormat = EvalOutputFormat.TEXT,
    ) -> str:
        if not isinstance(report, EvalReport):
            raise ValueError("report must be EvalReport.")
        if not isinstance(output_format, EvalOutputFormat):
            raise ValueError("output_format must be EvalOutputFormat.")
        payload = _payload(report)
        if output_format is EvalOutputFormat.JSON:
            return json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return _text(payload)


def _payload(report: EvalReport) -> dict[str, object]:
    run = report.run
    cases = []
    for case in report.case_results:
        failed_grades = [
            {
                "grader_id": grade.grader_id,
                "status": grade.status.value,
                "reason_code": grade.reason_code,
                "safe_explanation": grade.safe_explanation,
                "target_trace_id": grade.target_trace_id,
                "target_span_id": grade.target_span_id,
                "fact_references": list(grade.fact_references),
                "safe_expected": _json_value(grade.safe_expected),
                "safe_actual": _json_value(grade.safe_actual),
            }
            for grade in case.grade_results
            if grade.status
            in (
                GradeStatus.FAILED,
                GradeStatus.ERROR,
                GradeStatus.UNAVAILABLE,
            )
        ]
        cases.append(
            {
                "case_id": case.case_id,
                "status": case.status.value,
                "required": case.required,
                "duration_ms": case.duration_ms,
                "failure_classification": (
                    case.failure_classification.value
                    if case.failure_classification is not None
                    else None
                ),
                "target_trace_id": case.target_trace_id,
                "evaluator_trace_id": case.evaluator_trace_id,
                "inspector_identity": (
                    {"trace_id": case.target_trace_id}
                    if case.target_trace_id is not None
                    else None
                ),
                "failed_grades": failed_grades,
                "warnings": list(case.warnings),
            }
        )
    return {
        "run": {
            "eval_run_id": run.eval_run_id,
            "suite_id": run.suite_id,
            "suite_version": run.suite_version,
            "status": run.status.value,
            "environment_fingerprint": run.environment_fingerprint,
            "source_revision": run.source_revision,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
        },
        "counts": {
            "passed": report.counts.passed,
            "failed": report.counts.failed,
            "skipped": report.counts.skipped,
            "unavailable": report.counts.unavailable,
            "error": report.counts.error,
        },
        "cases": cases,
        "warnings": list(report.warnings),
    }


def _text(payload: dict[str, object]) -> str:
    run = payload["run"]
    counts = payload["counts"]
    lines = [
        f"Eval {run['eval_run_id']} suite={run['suite_id']} version={run['suite_version']}",
        f"status={run['status']} environment={run['environment_fingerprint']}",
        (
            "counts "
            f"passed={counts['passed']} failed={counts['failed']} "
            f"skipped={counts['skipped']} unavailable={counts['unavailable']} error={counts['error']}"
        ),
    ]
    for case in payload["cases"]:
        lines.append(
            f"case {case['case_id']} status={case['status']} classification={case['failure_classification'] or 'none'}"
        )
        for grade in case["failed_grades"]:
            target = grade["target_span_id"] or grade["target_trace_id"] or "unavailable"
            lines.append(
                f"  grader {grade['grader_id']} status={grade['status']} reason={grade['reason_code']} target={target}"
            )
    return "\n".join(lines)


def _json_value(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
