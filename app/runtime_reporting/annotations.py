"""Deterministic sample annotation rules over the one shared RuntimeReport."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.common.validation import require_non_empty_string
from app.observability.telemetry import AnnotationSink
from app.observability.trace_models import AnnotationRecord
from app.observability.trace_vocabulary import (
    AnnotationKind,
    AnnotationProducer,
    AnnotationSeverity,
    AnnotationStatus,
)
from app.runtime_reporting.models import RuntimeReport


@dataclass(frozen=True)
class AnnotationRunContext:
    created_at: str
    eval_run_id: str | None = None
    eval_suite_id: str | None = None
    eval_case_id: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_string(self.created_at, "created_at")


class RuntimeReportAnnotationRule(Protocol):
    def evaluate(
        self,
        report: RuntimeReport,
        context: AnnotationRunContext,
    ) -> tuple[AnnotationRecord, ...]: ...


class TraceIntegrityRule:
    rule_id = "trace_integrity"
    version = "1"

    def evaluate(
        self,
        report: RuntimeReport,
        context: AnnotationRunContext,
    ) -> tuple[AnnotationRecord, ...]:
        if not report.integrity_warnings:
            return ()
        fingerprint = _fingerprint(report, self.rule_id, report.integrity_warnings)
        return (
            AnnotationRecord(
                annotation_id=_annotation_id(
                    report.identity.trace_id, self.rule_id, fingerprint
                ),
                target_trace_id=report.identity.trace_id,
                annotation_kind=AnnotationKind.DIAGNOSTIC,
                producer=AnnotationProducer.DETERMINISTIC_RULE,
                evaluator_id=self.rule_id,
                producer_version=self.version,
                source_fingerprint=fingerprint,
                status=AnnotationStatus.WARNING,
                severity=AnnotationSeverity.WARNING,
                label="trace_integrity_invalid",
                reason_code="trace_integrity_invalid",
                safe_explanation="Trace integrity warnings require review.",
                created_at=context.created_at,
            ),
        )


class TraceContractGrader:
    grader_id = "trace_contract"
    version = "1"

    def evaluate(
        self,
        report: RuntimeReport,
        context: AnnotationRunContext,
    ) -> tuple[AnnotationRecord, ...]:
        lineage = (
            context.eval_run_id,
            context.eval_suite_id,
            context.eval_case_id,
        )
        if not all(lineage):
            raise ValueError("TraceContractGrader requires complete eval lineage.")
        passed = not report.integrity_warnings
        fingerprint = _fingerprint(
            report, self.grader_id, report.integrity_warnings
        )
        return (
            AnnotationRecord(
                annotation_id=_annotation_id(
                    report.identity.trace_id,
                    self.grader_id,
                    fingerprint,
                    *lineage,
                ),
                target_trace_id=report.identity.trace_id,
                annotation_kind=AnnotationKind.EVALUATION,
                producer=AnnotationProducer.DETERMINISTIC_RULE,
                evaluator_id=self.grader_id,
                producer_version=self.version,
                source_fingerprint=fingerprint,
                eval_run_id=context.eval_run_id,
                eval_suite_id=context.eval_suite_id,
                eval_case_id=context.eval_case_id,
                status=(
                    AnnotationStatus.PASSED if passed else AnnotationStatus.FAILED
                ),
                severity=(
                    AnnotationSeverity.INFO if passed else AnnotationSeverity.ERROR
                ),
                score=1.0 if passed else 0.0,
                label="trace_contract_valid" if passed else "trace_contract_invalid",
                reason_code=(
                    "trace_contract_valid" if passed else "trace_integrity_invalid"
                ),
                safe_explanation=(
                    "Trace contract is valid."
                    if passed
                    else "Trace contract contains integrity warnings."
                ),
                created_at=context.created_at,
            ),
        )


def persist_annotations(
    sink: AnnotationSink,
    annotations: tuple[AnnotationRecord, ...],
) -> tuple[str, ...]:
    """Persist independently; failures never mutate reports or target facts."""

    failed: list[str] = []
    for annotation in annotations:
        try:
            sink.record(annotation)
        except Exception:
            failed.append(annotation.annotation_id)
    return tuple(failed)


def _fingerprint(
    report: RuntimeReport,
    producer_id: str,
    warnings: tuple[str, ...],
) -> str:
    raw = "|".join(
        (
            report.identity.trace_id,
            report.identity.run_id,
            producer_id,
            *warnings,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _annotation_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"annotation_{digest}"
