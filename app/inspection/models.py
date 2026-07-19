"""Immutable Inspector-owned query, view, and result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.inspection.errors import InspectorValidationCode, InspectorValidationError
from app.observability.trace_models import AnnotationRecord
from app.observability.trace_reader import TraceGraph
from app.runtime_reporting import RuntimeReport


class InspectionView(StrEnum):
    SUMMARY = "summary"
    TREE = "tree"
    TIMELINE = "timeline"
    DETAILS = "details"
    GRAPH = "graph"
    EVIDENCE = "evidence"
    ANNOTATIONS = "annotations"
    INTEGRITY = "integrity"
    DIAGNOSE = "diagnose"


@dataclass(frozen=True)
class InspectionTarget:
    trace_id: str | None = None
    run_id: str | None = None
    plan_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        identities = (self.trace_id, self.run_id, self.plan_id)
        if sum(value is not None for value in identities) != 1:
            _invalid(
                "exactly one of trace_id, run_id, or plan_id is required.",
                InspectorValidationCode.TARGET_EXACTLY_ONE,
            )
        for name in ("trace_id", "run_id", "plan_id", "session_id"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)


@dataclass(frozen=True)
class InspectionQuery:
    target: InspectionTarget
    views: tuple[InspectionView, ...] = (InspectionView.SUMMARY,)
    span_id: str | None = None
    include_sensitive: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.target, InspectionTarget):
            _invalid("target must be an InspectionTarget.")
        _validate_views(self.views)
        if self.span_id is not None:
            _require_text(self.span_id, "span_id")
            if InspectionView.DETAILS not in self.views:
                _invalid(
                    "span_id requires the details view.",
                    InspectorValidationCode.SPAN_REQUIRES_DETAILS,
                )
            if self.target.plan_id is not None:
                _invalid(
                    "span_id cannot target a multi-trace plan query.",
                    InspectorValidationCode.SPAN_TARGET_AMBIGUOUS,
                )
        if not isinstance(self.include_sensitive, bool):
            _invalid("include_sensitive must be a bool.")
        if self.include_sensitive and InspectionView.DETAILS not in self.views:
            _invalid(
                "include_sensitive requires the details view.",
                InspectorValidationCode.SENSITIVE_REQUIRES_DETAILS,
            )


@dataclass(frozen=True)
class InspectionResult:
    target: InspectionTarget
    views: tuple[InspectionView, ...]
    trace_graphs: tuple[TraceGraph, ...]
    runtime_reports: tuple[RuntimeReport, ...]
    span_id: str | None = None
    include_sensitive: bool = False
    diagnostic_annotations: tuple[AnnotationRecord, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.target, InspectionTarget):
            _invalid("target must be an InspectionTarget.")
        _validate_views(self.views)
        if not isinstance(self.trace_graphs, tuple) or not all(
            isinstance(graph, TraceGraph) for graph in self.trace_graphs
        ):
            _invalid("trace_graphs must contain only TraceGraph values.")
        if not isinstance(self.runtime_reports, tuple):
            _invalid("runtime_reports must be a tuple.")
        if not self.runtime_reports:
            _invalid(
                "runtime_reports must not be empty.",
                InspectorValidationCode.REPORTS_REQUIRED,
            )
        if not all(isinstance(report, RuntimeReport) for report in self.runtime_reports):
            _invalid("runtime_reports must contain only RuntimeReport values.")
        trace_ids = tuple(report.identity.trace_id for report in self.runtime_reports)
        if len(set(trace_ids)) != len(trace_ids):
            _invalid(
                "runtime_reports must not repeat a trace.",
                InspectorValidationCode.DUPLICATE_REPORT,
            )
        if len(self.trace_graphs) != len(self.runtime_reports) or any(
            graph.trace.trace_id != report.identity.trace_id
            for graph, report in zip(self.trace_graphs, self.runtime_reports)
        ):
            _invalid(
                "trace_graphs and runtime_reports must align by trace identity.",
                InspectorValidationCode.TARGET_MISMATCH,
            )
        if self.span_id is not None:
            _require_text(self.span_id, "span_id")
            if InspectionView.DETAILS not in self.views:
                _invalid(
                    "span_id requires the details view.",
                    InspectorValidationCode.SPAN_REQUIRES_DETAILS,
                )
        if not isinstance(self.include_sensitive, bool):
            _invalid("include_sensitive must be a bool.")
        if self.include_sensitive and InspectionView.DETAILS not in self.views:
            _invalid(
                "include_sensitive requires the details view.",
                InspectorValidationCode.SENSITIVE_REQUIRES_DETAILS,
            )
        self._validate_target_alignment()
        if not isinstance(self.diagnostic_annotations, tuple):
            _invalid("diagnostic_annotations must be a tuple.")
        if not all(
            isinstance(annotation, AnnotationRecord)
            for annotation in self.diagnostic_annotations
        ):
            _invalid("diagnostic_annotations must contain AnnotationRecord values.")
        if any(
            annotation.target_trace_id not in trace_ids
            for annotation in self.diagnostic_annotations
        ):
            _invalid(
                "diagnostic annotation target must belong to a result trace.",
                InspectorValidationCode.ANNOTATION_TARGET_MISMATCH,
            )
        _validate_warnings(self.warnings)

    def _validate_target_alignment(self) -> None:
        identities = tuple(report.identity for report in self.runtime_reports)
        mismatch = False
        if self.target.trace_id is not None:
            mismatch = len(identities) != 1 or identities[0].trace_id != self.target.trace_id
        elif self.target.run_id is not None:
            mismatch = any(identity.run_id != self.target.run_id for identity in identities)
        if self.target.session_id is not None:
            mismatch = mismatch or any(
                identity.session_id != self.target.session_id for identity in identities
            )
        if mismatch:
            _invalid(
                "runtime reports do not match the inspection target.",
                InspectorValidationCode.TARGET_MISMATCH,
            )


def _validate_views(views: tuple[InspectionView, ...]) -> None:
    if not isinstance(views, tuple):
        _invalid("views must be a tuple.")
    if not views:
        _invalid("views must not be empty.", InspectorValidationCode.VIEWS_REQUIRED)
    if not all(isinstance(view, InspectionView) for view in views):
        _invalid("views must contain only InspectionView values.")
    if len(set(views)) != len(views):
        _invalid(
            "views must not contain duplicates.",
            InspectorValidationCode.DUPLICATE_VIEW,
        )


def _validate_warnings(warnings: tuple[str, ...]) -> None:
    if not isinstance(warnings, tuple):
        _invalid("warnings must be a tuple.")
    for warning in warnings:
        _require_text(warning, "warnings")
    if len(set(warnings)) != len(warnings):
        _invalid("warnings must not contain duplicates.")


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{field_name} must be a non-empty string.")


def _invalid(
    message: str,
    code: InspectorValidationCode = InspectorValidationCode.INVALID_FIELD,
) -> None:
    raise InspectorValidationError(message, code=code)
