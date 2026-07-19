"""Immutable evaluation, grading, aggregation, and report contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.common.validation import require_non_empty_string, require_unique_non_empty_strings
from app.evals.models import (
    FrozenJson,
    EvalCase,
    freeze_eval_object,
    require_stable_eval_id,
)
from app.evals.state import EvalStateDelta
from app.observability.trace_reader import TraceGraph
from app.runtime_reporting import RuntimeReport


class GradeStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class CaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class EvalRunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class FailureClassification(StrEnum):
    PRODUCT_FAILURE = "product_failure"
    HARNESS_ERROR = "harness_error"
    ENVIRONMENT_UNAVAILABLE = "environment_unavailable"


@dataclass(frozen=True)
class GradeResult:
    grade_id: str
    grader_id: str
    grader_version: str
    status: GradeStatus
    reason_code: str
    safe_explanation: str
    required: bool = True
    target_trace_id: str | None = None
    target_span_id: str | None = None
    fact_references: tuple[str, ...] = ()
    safe_expected: Mapping[str, FrozenJson] = field(default_factory=dict)
    safe_actual: Mapping[str, FrozenJson] = field(default_factory=dict)
    score: float | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        for name in ("grade_id", "grader_id"):
            require_stable_eval_id(getattr(self, name), name)
        for name in ("grader_version", "reason_code", "safe_explanation"):
            require_non_empty_string(getattr(self, name), name)
        if not isinstance(self.status, GradeStatus):
            raise ValueError("status must be GradeStatus.")
        if not isinstance(self.required, bool):
            raise ValueError("required must be a bool.")
        for name in ("target_trace_id", "target_span_id", "label"):
            value = getattr(self, name)
            if value is not None:
                require_non_empty_string(value, name)
        require_unique_non_empty_strings(self.fact_references, "fact_references")
        object.__setattr__(
            self, "safe_expected", freeze_eval_object(self.safe_expected, "safe_expected")
        )
        object.__setattr__(
            self, "safe_actual", freeze_eval_object(self.safe_actual, "safe_actual")
        )
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not 0 <= self.score <= 1
        ):
            raise ValueError("score must be between 0 and 1.")


@dataclass(frozen=True)
class EvaluationSubject:
    runtime_report: RuntimeReport
    trace_graph: TraceGraph | None = None
    state_delta: EvalStateDelta | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_report, RuntimeReport):
            raise ValueError("runtime_report must be RuntimeReport.")
        if self.trace_graph is not None:
            if not isinstance(self.trace_graph, TraceGraph):
                raise ValueError("trace_graph must be TraceGraph or None.")
            if self.trace_graph.trace.trace_id != self.runtime_report.identity.trace_id:
                raise ValueError("trace_graph and runtime_report must describe one trace.")
        if self.state_delta is not None and not isinstance(
            self.state_delta, EvalStateDelta
        ):
            raise ValueError("state_delta must be EvalStateDelta or None.")


class EvalGrader(Protocol):
    @property
    def grader_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult: ...


class EvalGraderRegistry:
    def __init__(self, graders: tuple[EvalGrader, ...]) -> None:
        if not isinstance(graders, tuple):
            raise ValueError("graders must be a tuple.")
        ids = tuple(grader.grader_id for grader in graders)
        require_unique_non_empty_strings(ids, "grader_ids")
        for grader_id in ids:
            require_stable_eval_id(grader_id, "grader_id")
        self._graders = dict(zip(ids, graders))

    @property
    def grader_ids(self) -> tuple[str, ...]:
        return tuple(self._graders)

    def get(self, grader_id: str) -> EvalGrader:
        require_stable_eval_id(grader_id, "grader_id")
        try:
            return self._graders[grader_id]
        except KeyError as exc:
            raise ValueError("grader_id is not registered.") from exc


@dataclass(frozen=True)
class EvalRun:
    eval_run_id: str
    suite_id: str
    suite_version: str
    environment_fingerprint: str
    started_at: str
    status: EvalRunStatus = EvalRunStatus.RUNNING
    ended_at: str | None = None
    source_revision: str | None = None

    def __post_init__(self) -> None:
        for name in ("eval_run_id", "suite_id"):
            require_stable_eval_id(getattr(self, name), name)
        for name in ("suite_version", "environment_fingerprint", "started_at"):
            require_non_empty_string(getattr(self, name), name)
        if not isinstance(self.status, EvalRunStatus):
            raise ValueError("status must be EvalRunStatus.")
        for name in ("ended_at", "source_revision"):
            value = getattr(self, name)
            if value is not None:
                require_non_empty_string(value, name)


@dataclass(frozen=True)
class CaseResult:
    eval_run_id: str
    suite_id: str
    case_id: str
    status: CaseStatus
    grade_results: tuple[GradeResult, ...]
    duration_ms: int
    required: bool = True
    target_trace_id: str | None = None
    evaluator_trace_id: str | None = None
    failure_classification: FailureClassification | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("eval_run_id", "suite_id", "case_id"):
            require_stable_eval_id(getattr(self, name), name)
        if not isinstance(self.status, CaseStatus):
            raise ValueError("status must be CaseStatus.")
        if not isinstance(self.grade_results, tuple) or not all(
            isinstance(item, GradeResult) for item in self.grade_results
        ):
            raise ValueError("grade_results must contain only GradeResult values.")
        grade_ids = tuple(item.grade_id for item in self.grade_results)
        if len(set(grade_ids)) != len(grade_ids):
            raise ValueError("grade_results must not repeat grade IDs.")
        if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool) or self.duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer.")
        if not isinstance(self.required, bool):
            raise ValueError("required must be a bool.")
        for name in ("target_trace_id", "evaluator_trace_id"):
            value = getattr(self, name)
            if value is not None:
                require_non_empty_string(value, name)
        if self.failure_classification is not None and not isinstance(
            self.failure_classification, FailureClassification
        ):
            raise ValueError("failure_classification must be typed.")
        require_unique_non_empty_strings(self.warnings, "warnings")


@dataclass(frozen=True)
class EvalCounts:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    unavailable: int = 0
    error: int = 0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("eval counts must be non-negative integers.")


@dataclass(frozen=True)
class EvalReport:
    run: EvalRun
    case_results: tuple[CaseResult, ...]
    counts: EvalCounts
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.run, EvalRun):
            raise ValueError("run must be EvalRun.")
        if not isinstance(self.case_results, tuple) or not all(
            isinstance(item, CaseResult) for item in self.case_results
        ):
            raise ValueError("case_results must contain only CaseResult values.")
        case_ids = tuple(item.case_id for item in self.case_results)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case_results must not repeat case IDs.")
        if not isinstance(self.counts, EvalCounts):
            raise ValueError("counts must be EvalCounts.")
        actual_counts = {
            status.value: sum(item.status is status for item in self.case_results)
            for status in CaseStatus
        }
        if any(getattr(self.counts, name) != count for name, count in actual_counts.items()):
            raise ValueError("counts must match case_results.")
        require_unique_non_empty_strings(self.warnings, "warnings")
