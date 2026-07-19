"""Typed read Ports for assembling canonical runtime facts."""

from __future__ import annotations

from typing import Protocol

from app.observability.trace_reader import TraceGraph
from app.runtime_reporting.models import RuntimeFactBundle


class RuntimeFactSource(Protocol):
    def load(self, trace: TraceGraph) -> RuntimeFactBundle: ...


class RuntimeFactProvider(Protocol):
    def load(self, trace: TraceGraph) -> RuntimeFactBundle: ...


class EmptyRuntimeFactProvider:
    def load(self, trace: TraceGraph) -> RuntimeFactBundle:
        if not isinstance(trace, TraceGraph):
            raise ValueError("trace must be a TraceGraph.")
        return RuntimeFactBundle()


class CompositeRuntimeFactProvider:
    """Merge typed source bundles without querying raw tables or artifacts."""

    def __init__(self, sources: tuple[RuntimeFactSource, ...]) -> None:
        if not isinstance(sources, tuple):
            raise ValueError("sources must be a tuple.")
        self._sources = sources

    def load(self, trace: TraceGraph) -> RuntimeFactBundle:
        bundles = tuple(source.load(trace) for source in self._sources)
        return RuntimeFactBundle(
            run_record=_one_optional(bundles, "run_record"),
            plan_runs_and_steps=_combine(bundles, "plan_runs_and_steps"),
            workflow_state=_one_optional(bundles, "workflow_state"),
            execution_feedback=_one_optional(bundles, "execution_feedback"),
            recovery_result=_one_optional(bundles, "recovery_result"),
            final_answer_validation=_one_optional(
                bundles, "final_answer_validation"
            ),
            stop_point=_one_optional(bundles, "stop_point"),
            execution_feedback_evidence=_combine(
                bundles, "execution_feedback_evidence"
            ),
            evidence_reports=_combine(bundles, "evidence_reports"),
            fact_source_warnings=_combine(bundles, "fact_source_warnings"),
        )


def _one_optional(bundles: tuple[RuntimeFactBundle, ...], field_name: str):
    values = tuple(
        value
        for bundle in bundles
        if (value := getattr(bundle, field_name)) is not None
    )
    if len(values) > 1:
        raise ValueError(f"multiple fact sources own {field_name}.")
    return values[0] if values else None


def _combine(bundles: tuple[RuntimeFactBundle, ...], field_name: str):
    return tuple(item for bundle in bundles for item in getattr(bundle, field_name))
