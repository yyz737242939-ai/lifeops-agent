"""Deterministic diagnostic rules over the one shared RuntimeReport."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Protocol

from app.observability.trace_models import AnnotationRecord
from app.observability.trace_vocabulary import (
    AnnotationKind,
    AnnotationProducer,
    AnnotationSeverity,
    AnnotationStatus,
)
from app.runtime_reporting import FactProjection, RuntimeReport
from app.runtime_reporting.annotations import AnnotationRunContext


class DiagnosticRule(Protocol):
    @property
    def rule_id(self) -> str: ...

    def evaluate(
        self,
        report: RuntimeReport,
        context: AnnotationRunContext,
    ) -> tuple[AnnotationRecord, ...]: ...


@dataclass(frozen=True)
class DiagnosticRegistryResult:
    annotations: tuple[AnnotationRecord, ...]
    warnings: tuple[str, ...]


class DiagnosticRegistry:
    def __init__(self, rules: tuple[DiagnosticRule, ...]) -> None:
        if not isinstance(rules, tuple) or not rules:
            raise ValueError("rules must be a non-empty tuple.")
        rule_ids = tuple(rule.rule_id for rule in rules)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("diagnostic rule IDs must be unique.")
        self._rules = rules

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.rule_id for rule in self._rules)

    @property
    def rules(self) -> tuple[DiagnosticRule, ...]:
        return self._rules

    def evaluate(
        self,
        report: RuntimeReport,
        context: AnnotationRunContext,
    ) -> DiagnosticRegistryResult:
        annotations: list[AnnotationRecord] = []
        warnings: list[str] = []
        for rule in self._rules:
            try:
                annotations.extend(rule.evaluate(report, context))
            except Exception:
                warnings.append(f"diagnostic_rule_failed:{rule.rule_id}")
        return DiagnosticRegistryResult(tuple(annotations), tuple(warnings))


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    predicate: Callable[[RuntimeReport], tuple[FactProjection | None, ...]]
    severity: AnnotationSeverity = AnnotationSeverity.WARNING
    version: str = "1"

    def evaluate(
        self,
        report: RuntimeReport,
        context: AnnotationRunContext,
    ) -> tuple[AnnotationRecord, ...]:
        targets = self.predicate(report)
        if not targets:
            return ()
        annotations = []
        for index, target in enumerate(targets):
            target_id = target.source_id if target is not None else report.identity.trace_id
            fingerprint = hashlib.sha256(
                "|".join(
                    (
                        report.identity.trace_id,
                        report.identity.run_id,
                        self.rule_id,
                        target_id,
                        *report.integrity_warnings,
                    )
                ).encode("utf-8")
            ).hexdigest()
            annotation_id = "annotation_" + hashlib.sha256(
                f"{self.rule_id}|{fingerprint}|{index}".encode("utf-8")
            ).hexdigest()
            annotations.append(
                AnnotationRecord(
                    annotation_id=annotation_id,
                    target_trace_id=report.identity.trace_id,
                    target_span_id=_target_span_id(target),
                    annotation_kind=AnnotationKind.DIAGNOSTIC,
                    producer=AnnotationProducer.DETERMINISTIC_RULE,
                    evaluator_id=self.rule_id,
                    producer_version=self.version,
                    source_fingerprint=fingerprint,
                    status=AnnotationStatus.WARNING,
                    severity=self.severity,
                    label=self.rule_id,
                    reason_code=self.rule_id,
                    safe_explanation=_EXPLANATIONS[self.rule_id],
                    created_at=context.created_at,
                )
            )
        return tuple(annotations)


def default_diagnostic_registry() -> DiagnosticRegistry:
    return DiagnosticRegistry(
        (
            _Rule("trace_integrity_invalid", _trace_integrity),
            _Rule("first_failure", _first_failure, AnnotationSeverity.ERROR),
            _Rule("unsupported_success_claim", _unsupported_success_claim, AnnotationSeverity.ERROR),
            _Rule("missing_write_evidence", _missing_write_evidence, AnnotationSeverity.ERROR),
            _Rule("policy_tool_mismatch", _policy_tool_mismatch, AnnotationSeverity.ERROR),
            _Rule("confirmation_boundary_violation", _confirmation_violation, AnnotationSeverity.CRITICAL),
            _Rule("repeated_action_no_progress", _repeated_no_progress),
            _Rule("downstream_blocked", _downstream_blocked),
            _Rule("source_conflict", _source_conflict, AnnotationSeverity.ERROR),
            _Rule("sensitive_data_exposed", _sensitive_data_exposed, AnnotationSeverity.CRITICAL),
        )
    )


def _trace_integrity(report: RuntimeReport) -> tuple[None, ...]:
    integrity_prefixes = (
        "missing_parent",
        "unexpected_root",
        "cycle",
        "duplicate",
        "missing_event_span",
        "missing_link_source",
        "missing_link_target",
        "missing_artifact_span",
        "missing_annotation_span",
        "source_corrupt",
    )
    return (
        (None,)
        if any(
            warning.startswith(integrity_prefixes)
            for warning in report.integrity_warnings
        )
        else ()
    )


def _first_failure(report: RuntimeReport) -> tuple[FactProjection, ...]:
    candidates = report.plan_report + report.executor_invocations + report.tool_attempts
    return tuple(item for item in candidates if _outcome(item) in {"failed", "error"})[:1]


def _unsupported_success_claim(report: RuntimeReport) -> tuple[FactProjection, ...]:
    item = report.final_answer_validation
    return (item,) if item is not None and _outcome(item) in {"failed", "invalid"} else ()


def _missing_write_evidence(report: RuntimeReport) -> tuple[FactProjection, ...]:
    return tuple(
        item
        for item in report.tool_attempts
        if item.attributes.get("lifeops.tool.effect") == "write"
        and _outcome(item) in {"ok", "success", "succeeded"}
        and int(item.attributes.get("lifeops.tool.evidence.count", 0)) == 0
    )


def _policy_tool_mismatch(report: RuntimeReport) -> tuple[FactProjection, ...]:
    return tuple(
        item
        for item in report.tool_attempts
        if item.attributes.get("lifeops.tool.allowed") is False
        or item.attributes.get("lifeops.policy.allowed") is False
    )


def _confirmation_violation(
    report: RuntimeReport,
) -> tuple[FactProjection | None, ...]:
    flagged = tuple(
        item
        for item in report.tool_attempts
        if item.attributes.get("lifeops.tool.effect") == "write"
        and item.attributes.get("lifeops.confirmation.valid") is False
    )
    return flagged or (
        (None,)
        if "confirmation_boundary_violation" in report.integrity_warnings
        else ()
    )


def _repeated_no_progress(report: RuntimeReport) -> tuple[FactProjection | None, ...]:
    flagged = tuple(
        item
        for item in report.executor_invocations + report.tool_attempts
        if item.attributes.get("lifeops.executor.no_progress") is True
    )
    return flagged or ((None,) if "repeated_action_no_progress" in report.integrity_warnings else ())


def _downstream_blocked(report: RuntimeReport) -> tuple[FactProjection, ...]:
    return tuple(
        item
        for item in report.plan_report + report.executor_invocations
        if _outcome(item) in {"blocked", "skipped", "not_run", "not-run"}
    )


def _source_conflict(report: RuntimeReport) -> tuple[None, ...]:
    return (None,) if any("source_conflict" in item for item in report.integrity_warnings) else ()


def _sensitive_data_exposed(report: RuntimeReport) -> tuple[FactProjection | None, ...]:
    forbidden = ("prompt", "arguments", "output", "exception", "memory", "profile")
    projections = (
        report.plan_report
        + report.executor_invocations
        + report.tool_attempts
        + report.workflow_dependencies
    )
    flagged = tuple(
        item
        for item in projections
        if any(any(token in key.lower() for token in forbidden) for key in item.attributes)
    )
    return flagged or ((None,) if "sensitive_data_exposed" in report.integrity_warnings else ())


def _outcome(item: FactProjection) -> str:
    return str(
        item.attributes.get("lifeops.workflow.node.outcome")
        or item.attributes.get("lifeops.plan.step.outcome")
        or item.attributes.get("lifeops.tool.outcome")
        or item.status
    ).lower()


def _target_span_id(target: FactProjection | None) -> str | None:
    if target is None or not target.source_kind.startswith("trace_span:"):
        return None
    return target.source_id


_EXPLANATIONS = {
    "trace_integrity_invalid": "Trace integrity warnings require review.",
    "first_failure": "The first confirmed failure is identified by shared runtime facts.",
    "unsupported_success_claim": "Final-answer validation rejected an unsupported success claim.",
    "missing_write_evidence": "A successful WRITE fact lacks matching execution evidence.",
    "policy_tool_mismatch": "A Tool attempt conflicts with the projected Policy boundary.",
    "confirmation_boundary_violation": "A WRITE attempt conflicts with the projected confirmation boundary.",
    "repeated_action_no_progress": "Repeated execution made no confirmed progress.",
    "downstream_blocked": "Downstream work is blocked or was not run.",
    "source_conflict": "Shared fact sources disagree and require conservative handling.",
    "sensitive_data_exposed": "Protected content appears in a non-sensitive shared projection.",
}
