"""Immutable shared read models above low-level observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.common.validation import require_non_empty_string
from app.observability.trace_models import (
    AnnotationRecord,
    FrozenMetadata,
    freeze_metadata,
)


@dataclass(frozen=True)
class ReportIdentity:
    trace_id: str
    run_id: str
    session_id: str
    turn_id: str

    def __post_init__(self) -> None:
        for name in ("trace_id", "run_id", "session_id", "turn_id"):
            require_non_empty_string(getattr(self, name), name)


@dataclass(frozen=True)
class FactProjection:
    source_kind: str
    source_id: str
    status: str
    attributes: FrozenMetadata | Mapping[str, object] = field(
        default_factory=FrozenMetadata
    )

    def __post_init__(self) -> None:
        for name in ("source_kind", "source_id", "status"):
            require_non_empty_string(getattr(self, name), name)
        object.__setattr__(self, "attributes", freeze_metadata(self.attributes))


@dataclass(frozen=True)
class EvidenceReport:
    source_kind: str
    source_id: str
    reference: str | None = None
    status: str = "available"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("source_kind", "source_id", "status"):
            require_non_empty_string(getattr(self, name), name)
        if self.reference is not None:
            require_non_empty_string(self.reference, "reference")
        if not isinstance(self.warnings, tuple):
            raise ValueError("warnings must be a tuple.")
        for warning in self.warnings:
            require_non_empty_string(warning, "warnings")


@dataclass(frozen=True)
class RuntimeFactBundle:
    run_record: FactProjection | None = None
    plan_runs_and_steps: tuple[FactProjection, ...] = ()
    workflow_state: FactProjection | None = None
    execution_feedback: FactProjection | None = None
    recovery_result: FactProjection | None = None
    final_answer_validation: FactProjection | None = None
    stop_point: FactProjection | None = None
    execution_feedback_evidence: tuple[FactProjection, ...] = ()
    evidence_reports: tuple[EvidenceReport, ...] = ()
    fact_source_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        tuple_fields = (
            "plan_runs_and_steps",
            "execution_feedback_evidence",
            "evidence_reports",
            "fact_source_warnings",
        )
        for name in tuple_fields:
            if not isinstance(getattr(self, name), tuple):
                raise ValueError(f"{name} must be a tuple.")


@dataclass(frozen=True)
class RuntimeReport:
    identity: ReportIdentity
    route: str | None
    intent_decision: FactProjection | None
    policy_decision: FactProjection | None
    selected_skills: tuple[str, ...]
    context_report: FactProjection | None
    plan_report: tuple[FactProjection, ...]
    workflow_report: FactProjection | None
    executor_invocations: tuple[FactProjection, ...]
    tool_attempts: tuple[FactProjection, ...]
    execution_feedback: FactProjection | None
    recovery_report: FactProjection | None
    evidence: tuple[EvidenceReport, ...]
    final_answer_validation: FactProjection | None
    stop_point: FactProjection | None
    diagnostic_annotations: tuple[AnnotationRecord, ...]
    evaluation_annotations: tuple[AnnotationRecord, ...]
    integrity_warnings: tuple[str, ...]
    workflow_dependencies: tuple[FactProjection, ...] = ()
