"""Read-only composition of shared trace and runtime-report boundaries."""

from __future__ import annotations

from datetime import datetime, timezone

from app.inspection.errors import InspectorError, InspectorErrorCode
from app.inspection.diagnostics import DiagnosticRegistry
from app.inspection.models import InspectionQuery, InspectionResult
from app.inspection.ports import InspectionReportBuilder, InspectionTraceReader
from app.observability.telemetry import AnnotationSink
from app.runtime_reporting import RuntimeFactBundle, RuntimeFactProvider
from app.runtime_reporting.annotations import (
    AnnotationRunContext,
    persist_annotations,
)


class InspectorService:
    def __init__(
        self,
        *,
        trace_reader: InspectionTraceReader,
        fact_provider: RuntimeFactProvider,
        report_builder: InspectionReportBuilder,
        diagnostic_registry: DiagnosticRegistry | None = None,
        diagnostic_context: AnnotationRunContext | None = None,
        annotation_sink: AnnotationSink | None = None,
    ) -> None:
        self._trace_reader = trace_reader
        self._fact_provider = fact_provider
        self._report_builder = report_builder
        self._diagnostic_registry = diagnostic_registry
        self._diagnostic_context = diagnostic_context or AnnotationRunContext(
            created_at=datetime.now(timezone.utc).isoformat()
        )
        self._annotation_sink = annotation_sink

    def inspect(self, query: InspectionQuery) -> InspectionResult:
        if not isinstance(query, InspectionQuery):
            raise ValueError("query must be an InspectionQuery.")
        graphs = self._resolve(query)
        reports = []
        for graph in graphs:
            try:
                facts = self._fact_provider.load(graph)
            except Exception:
                facts = RuntimeFactBundle(
                    fact_source_warnings=("fact_provider_unavailable",)
                )
            try:
                reports.append(self._report_builder.build(graph, facts))
            except Exception as exc:
                raise InspectorError(
                    "A runtime report could not be built for the inspection target.",
                    code=InspectorErrorCode.REPORT_BUILDER_FAILED,
                ) from exc
        annotations = []
        warnings = []
        if self._diagnostic_registry is not None and any(
            view.value == "diagnose" for view in query.views
        ):
            for report in reports:
                diagnostic = self._diagnostic_registry.evaluate(
                    report, self._diagnostic_context
                )
                annotations.extend(diagnostic.annotations)
                warnings.extend(diagnostic.warnings)
        if self._annotation_sink is not None and annotations:
            failed = persist_annotations(self._annotation_sink, tuple(annotations))
            warnings.extend(f"annotation_not_persisted:{item}" for item in failed)
        return InspectionResult(
            target=query.target,
            views=query.views,
            trace_graphs=graphs,
            runtime_reports=tuple(reports),
            span_id=query.span_id,
            include_sensitive=query.include_sensitive,
            diagnostic_annotations=tuple(annotations),
            warnings=tuple(warnings),
        )

    def _resolve(self, query: InspectionQuery):
        target = query.target
        try:
            if target.trace_id is not None:
                graphs = (self._trace_reader.get_trace(target.trace_id),)
            elif target.run_id is not None:
                graphs = (self._trace_reader.find_by_run(target.run_id),)
            else:
                graphs = self._trace_reader.find_by_plan(target.plan_id or "")
        except Exception as exc:
            raise InspectorError(
                "The inspection target is unavailable.",
                code=InspectorErrorCode.TARGET_NOT_FOUND,
            ) from exc
        if not graphs:
            raise InspectorError(
                "The inspection target is unavailable.",
                code=InspectorErrorCode.TARGET_NOT_FOUND,
            )
        return graphs
