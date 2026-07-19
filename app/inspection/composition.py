"""Production-facing read-only composition for the local Inspector."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.inspection.diagnostics import DiagnosticRegistry
from app.inspection.service import InspectorService
from app.observability.trace_reader import FileTraceStore, TraceGraph, TraceReader
from app.runtime_reporting import (
    EmptyRuntimeFactProvider,
    RuntimeFactProvider,
    RuntimeReportBuilder,
)


DEFAULT_TRACE_INDEX = Path("index/lifeops_trace_index.sqlite3")


class FallbackAwareTraceReader:
    """Delegate reconstruction to TraceReader and add source availability context."""

    def __init__(self, store: FileTraceStore) -> None:
        self._store = store
        self._reader = TraceReader(store)

    def get_trace(self, trace_id: str) -> TraceGraph:
        return self._decorate(self._reader.get_trace(trace_id))

    def find_by_run(self, run_id: str) -> TraceGraph:
        return self._decorate(self._reader.find_by_run(run_id))

    def find_by_plan(self, plan_id: str) -> tuple[TraceGraph, ...]:
        return tuple(self._decorate(graph) for graph in self._reader.find_by_plan(plan_id))

    def _decorate(self, graph: TraceGraph) -> TraceGraph:
        if self._store.index_path is None or self._store.load_source(graph.trace.trace_id) != "file":
            return graph
        return replace(
            graph,
            integrity_warnings=tuple(
                sorted(set(graph.integrity_warnings + ("index_unavailable",)))
            ),
        )


def build_inspector_service(
    log_root: str | Path,
    *,
    index_path: str | Path | None = None,
    fact_provider: RuntimeFactProvider | None = None,
    diagnostic_registry: DiagnosticRegistry | None = None,
) -> InspectorService:
    root = Path(log_root)
    resolved_index = Path(index_path) if index_path is not None else root / DEFAULT_TRACE_INDEX
    reader = FallbackAwareTraceReader(
        FileTraceStore(root, index_path=resolved_index)
    )
    return InspectorService(
        trace_reader=reader,
        fact_provider=fact_provider or EmptyRuntimeFactProvider(),
        report_builder=RuntimeReportBuilder(),
        diagnostic_registry=diagnostic_registry,
    )
