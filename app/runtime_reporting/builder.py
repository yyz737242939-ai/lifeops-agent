"""Deterministic shared RuntimeReport construction from TraceGraph and facts."""

from __future__ import annotations

from app.observability.trace_reader import TraceGraph
from app.observability.trace_vocabulary import AnnotationKind, LifeOpsSpanKind
from app.runtime_reporting.models import (
    EvidenceReport,
    FactProjection,
    ReportIdentity,
    RuntimeFactBundle,
    RuntimeReport,
)


class RuntimeReportBuilder:
    def build(self, trace: TraceGraph, facts: RuntimeFactBundle) -> RuntimeReport:
        if not isinstance(trace, TraceGraph):
            raise ValueError("trace must be a TraceGraph.")
        if not isinstance(facts, RuntimeFactBundle):
            raise ValueError("facts must be a RuntimeFactBundle.")
        spans = tuple(
            sorted(
                trace.spans_by_id.values(),
                key=lambda span: (span.started_at, span.span_id),
            )
        )
        executors = tuple(
            _span_projection(span)
            for span in spans
            if span.lifeops_span_kind is LifeOpsSpanKind.EXECUTOR
        )
        tools = tuple(
            _span_projection(span)
            for span in spans
            if span.lifeops_span_kind is LifeOpsSpanKind.TOOL
        )
        evidence = tuple(
            EvidenceReport(
                source_kind="artifact_reference",
                source_id=artifact.artifact_id,
                reference=artifact.safe_reference,
                status="available",
            )
            for artifact in trace.artifacts
            if artifact.artifact_type == "tool_evidence"
        ) + facts.evidence_reports
        diagnostic = tuple(
            item
            for item in trace.annotations
            if item.annotation_kind
            in (AnnotationKind.DIAGNOSTIC, AnnotationKind.WARNING)
        )
        evaluation = tuple(
            item
            for item in trace.annotations
            if item.annotation_kind is AnnotationKind.EVALUATION
        )
        return RuntimeReport(
            identity=ReportIdentity(
                trace.trace.trace_id,
                trace.trace.run_id,
                trace.trace.session_id,
                trace.trace.turn_id,
            ),
            route=None,
            intent_decision=None,
            policy_decision=None,
            selected_skills=(),
            context_report=_first_kind(spans, LifeOpsSpanKind.CONTEXT),
            plan_report=facts.plan_runs_and_steps,
            workflow_report=facts.workflow_state or _workflow_projection(spans),
            executor_invocations=executors,
            tool_attempts=tools,
            execution_feedback=facts.execution_feedback,
            recovery_report=facts.recovery_result,
            evidence=evidence,
            final_answer_validation=None,
            stop_point=facts.execution_feedback,
            diagnostic_annotations=diagnostic,
            evaluation_annotations=evaluation,
            integrity_warnings=tuple(
                sorted(
                    set(trace.integrity_warnings + facts.fact_source_warnings)
                )
            ),
        )


def _span_projection(span) -> FactProjection:
    return FactProjection(
        source_kind=f"trace_span:{span.lifeops_span_kind.value}",
        source_id=span.span_id,
        status=span.status.value,
        attributes=span.attributes,
    )


def _first_kind(spans, kind: LifeOpsSpanKind) -> FactProjection | None:
    matches = tuple(span for span in spans if span.lifeops_span_kind is kind)
    return _span_projection(matches[0]) if matches else None


def _workflow_projection(spans) -> FactProjection | None:
    matches = tuple(
        span for span in spans if "lifeops.workflow.id" in span.attributes
    )
    scheduler = next(
        (
            span
            for span in matches
            if "lifeops.workflow.node.id" not in span.attributes
        ),
        None,
    )
    return _span_projection(scheduler) if scheduler is not None else None
