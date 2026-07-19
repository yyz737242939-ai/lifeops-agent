"""Narrow read-only ports consumed by InspectorService."""

from __future__ import annotations

from typing import Protocol

from app.observability.trace_reader import TraceGraph
from app.runtime_reporting import RuntimeFactBundle, RuntimeReport


class InspectionTraceReader(Protocol):
    def get_trace(self, trace_id: str) -> TraceGraph: ...

    def find_by_run(self, run_id: str) -> TraceGraph: ...

    def find_by_plan(self, plan_id: str) -> tuple[TraceGraph, ...]: ...


class InspectionReportBuilder(Protocol):
    def build(self, trace: TraceGraph, facts: RuntimeFactBundle) -> RuntimeReport: ...
