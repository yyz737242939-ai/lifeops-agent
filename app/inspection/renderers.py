"""Deterministic safe text and JSON rendering for Inspector results."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum

from app.inspection.models import InspectionResult, InspectionView
from app.observability.trace_vocabulary import SpanLinkType


class InspectionOutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


class InspectionRenderer:
    def render(
        self,
        result: InspectionResult,
        output_format: InspectionOutputFormat = InspectionOutputFormat.TEXT,
    ) -> str:
        if not isinstance(result, InspectionResult):
            raise ValueError("result must be an InspectionResult.")
        if not isinstance(output_format, InspectionOutputFormat):
            raise ValueError("output_format must be an InspectionOutputFormat.")
        payload = {
            "target": _target(result),
            "sections": _sections(result),
            "warnings": list(result.warnings),
        }
        if output_format is InspectionOutputFormat.JSON:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return _render_text(payload)


def _sections(result: InspectionResult) -> dict[str, object]:
    sections: dict[str, object] = {}
    pairs = tuple(zip(result.trace_graphs, result.runtime_reports))
    for view in result.views:
        if view is InspectionView.SUMMARY:
            sections[view.value] = [_summary(report) for _graph, report in pairs]
        elif view is InspectionView.TREE:
            sections[view.value] = [_tree(graph) for graph, _report in pairs]
        elif view is InspectionView.TIMELINE:
            sections[view.value] = [_timeline(graph) for graph, _report in pairs]
        elif view is InspectionView.DETAILS:
            sections[view.value] = [
                _details(graph, result.span_id) for graph, _report in pairs
            ]
        elif view is InspectionView.GRAPH:
            sections[view.value] = [_graph_view(graph) for graph, _report in pairs]
        elif view is InspectionView.EVIDENCE:
            sections[view.value] = [
                _evidence(graph, report, result.include_sensitive)
                for graph, report in pairs
            ]
        elif view is InspectionView.ANNOTATIONS:
            sections[view.value] = [
                _annotations(report, result.diagnostic_annotations)
                for _graph, report in pairs
            ]
        elif view is InspectionView.INTEGRITY:
            sections[view.value] = [
                {
                    "trace_id": report.identity.trace_id,
                    "status": "valid" if not report.integrity_warnings else "warning",
                    "warnings": list(report.integrity_warnings),
                }
                for _graph, report in pairs
            ]
        elif view is InspectionView.DIAGNOSE:
            sections[view.value] = [
                _annotation_rows(
                    tuple(
                        item
                        for item in result.diagnostic_annotations
                        if item.target_trace_id == report.identity.trace_id
                    )
                )
                for _graph, report in pairs
            ]
    return sections


def _target(result: InspectionResult) -> dict[str, str]:
    return {
        key: value
        for key in ("trace_id", "run_id", "plan_id", "session_id")
        if (value := getattr(result.target, key)) is not None
    }


def _summary(report) -> dict[str, object]:
    return {
        "trace_id": report.identity.trace_id,
        "run_id": report.identity.run_id,
        "session_id": report.identity.session_id,
        "turn_id": report.identity.turn_id,
        "route": report.route or "unavailable",
        "executor_invocation_count": len(report.executor_invocations),
        "tool_attempt_count": len(report.tool_attempts),
        "evidence_count": len(report.evidence),
        "execution_feedback_status": (
            report.execution_feedback.status
            if report.execution_feedback is not None
            else "unavailable"
        ),
        "stop_status": report.stop_point.status if report.stop_point is not None else "unavailable",
        "trace_integrity": "valid" if not report.integrity_warnings else "warning",
    }


def _tree(graph) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def visit(span, depth: int) -> None:
        rows.append(
            {
                "depth": depth,
                "span_id": span.span_id,
                "kind": span.lifeops_span_kind.value,
                "name": span.name,
                "status": span.status.value,
                "error_code": span.error_code,
                "duration_ms": _duration_ms(span.started_at, span.ended_at),
            }
        )
        for child in graph.children_by_parent.get(span.span_id, ()):
            visit(child, depth + 1)

    visit(graph.root_span, 0)
    return rows


def _timeline(graph) -> list[dict[str, object]]:
    items = [
        {
            "record_type": "span",
            "identity": span.span_id,
            "timestamp": span.started_at,
            "name": span.name,
            "status": span.status.value,
            "duration_ms": _duration_ms(span.started_at, span.ended_at),
        }
        for span in graph.spans_by_id.values()
    ]
    items.extend(
        {
            "record_type": "event",
            "identity": event.event_id,
            "timestamp": event.timestamp,
            "name": event.name,
            "status": event.level,
            "duration_ms": None,
        }
        for event in graph.events
    )
    return sorted(items, key=lambda item: (str(item["timestamp"]), str(item["identity"])))


def _details(graph, span_id: str | None) -> list[dict[str, object]]:
    if span_id is not None:
        span = graph.spans_by_id.get(span_id)
        spans = (span,) if span is not None else ()
    else:
        spans = tuple(
            sorted(graph.spans_by_id.values(), key=lambda item: (item.started_at, item.span_id))
        )
    return [
        {
            "span_id": span.span_id,
            "parent_span_id": span.parent_span_id,
            "kind": span.lifeops_span_kind.value,
            "name": span.name,
            "status": span.status.value,
            "error_code": span.error_code,
            "started_at": span.started_at,
            "ended_at": span.ended_at,
            "duration_ms": _duration_ms(span.started_at, span.ended_at),
            "attributes": _safe_attributes(span.attributes),
            "event_ids": [event.event_id for event in graph.events if event.span_id == span.span_id],
            "link_ids": [
                link.link_id
                for link in graph.links
                if link.source_span_id == span.span_id or link.target_span_id == span.span_id
            ],
            "artifact_ids": [
                artifact.artifact_id for artifact in graph.artifacts if artifact.span_id == span.span_id
            ],
            "annotation_ids": [
                annotation.annotation_id
                for annotation in graph.annotations
                if annotation.target_span_id == span.span_id
            ],
        }
        for span in spans
        if span is not None
    ]


def _graph_view(graph) -> list[dict[str, object]]:
    dependency_links = tuple(
        link for link in graph.links if link.link_type is SpanLinkType.DEPENDS_ON
    )
    node_span_ids = {
        identity
        for link in dependency_links
        for identity in (link.source_span_id, link.target_span_id)
        if identity is not None
    }
    node_span_ids.update(
        span.span_id
        for span in graph.spans_by_id.values()
        if "lifeops.workflow.node.id" in span.attributes
        or "lifeops.plan.step.id" in span.attributes
    )
    rows = []
    for span in sorted(
        (graph.spans_by_id[span_id] for span_id in node_span_ids if span_id in graph.spans_by_id),
        key=lambda item: (item.started_at, item.span_id),
    ):
        dependencies = tuple(
            sorted(
                link.target_span_id
                for link in dependency_links
                if link.source_span_id == span.span_id and link.target_span_id is not None
            )
        )
        dependency_outcomes = {
            dependency: _span_outcome(graph.spans_by_id.get(dependency))
            for dependency in dependencies
        }
        rows.append(
            {
                "node_id": (
                    span.attributes.get("lifeops.workflow.node.id")
                    or span.attributes.get("lifeops.plan.step.id")
                    or span.span_id
                ),
                "span_id": span.span_id,
                "dependencies": list(dependencies),
                "outcome": _span_outcome(span),
                "evidence": [
                    artifact.artifact_id
                    for artifact in graph.artifacts
                    if artifact.span_id == span.span_id
                ],
                "blocked_by": [
                    dependency
                    for dependency, outcome in dependency_outcomes.items()
                    if outcome in {"failed", "blocked", "skipped", "not_run"}
                ],
            }
        )
    return rows


def _evidence(graph, report, include_sensitive: bool) -> dict[str, object]:
    return {
        "artifact_references": [
            {
                "artifact_id": artifact.artifact_id,
                "span_id": artifact.span_id,
                "artifact_type": artifact.artifact_type,
                "storage_kind": artifact.storage_kind,
                "safe_reference": artifact.safe_reference,
                "sensitivity": artifact.sensitivity.value,
                "content_hash": artifact.content_hash,
                "availability": "metadata_only",
                "content_included": False,
            }
            for artifact in graph.artifacts
        ],
        "runtime_evidence": [
            {
                "source_kind": item.source_kind,
                "source_id": item.source_id,
                "reference": item.reference,
                "status": item.status,
                "warnings": list(item.warnings),
            }
            for item in report.evidence
        ],
        "sensitive_access": (
            "not_configured" if include_sensitive else "not_requested"
        ),
    }


def _annotations(report, ephemeral) -> dict[str, object]:
    return {
        "persisted_diagnostic": _annotation_rows(report.diagnostic_annotations),
        "persisted_evaluation": _annotation_rows(report.evaluation_annotations),
        "ephemeral_diagnostic": _annotation_rows(
            tuple(
                item
                for item in ephemeral
                if item.target_trace_id == report.identity.trace_id
            )
        ),
    }


def _annotation_rows(annotations) -> list[dict[str, object]]:
    return [
        {
            "annotation_id": item.annotation_id,
            "target_trace_id": item.target_trace_id,
            "target_span_id": item.target_span_id,
            "kind": item.annotation_kind.value,
            "producer": item.producer.value,
            "status": item.status.value,
            "severity": item.severity.value if item.severity is not None else None,
            "reason_code": item.reason_code,
            "safe_explanation": item.safe_explanation,
            "source_fingerprint": item.source_fingerprint,
        }
        for item in annotations
    ]


def _safe_attributes(attributes) -> dict[str, object]:
    forbidden = (
        "prompt",
        "user_input",
        "arguments",
        "output",
        "confirmation",
        "credential",
        "password",
        "secret",
        "private_reasoning",
        "chain_of_thought",
        "exception",
        "memory",
        "profile",
        "context.content",
        "message",
        "text",
    )
    return {
        key: value
        for key, value in attributes.items()
        if not any(token in key.lower() for token in forbidden)
    }


def _span_outcome(span) -> str:
    if span is None:
        return "unavailable"
    return str(
        span.attributes.get("lifeops.workflow.node.outcome")
        or span.attributes.get("lifeops.plan.step.outcome")
        or span.status.value
    )


def _duration_ms(started_at: str, ended_at: str | None) -> int | None:
    if ended_at is None:
        return None
    delta = datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)
    return round(delta.total_seconds() * 1000)


def _render_text(payload: dict[str, object]) -> str:
    lines = ["LifeOps Inspector", f"target: {json.dumps(payload['target'], sort_keys=True)}"]
    sections = payload["sections"]
    assert isinstance(sections, dict)
    for name, content in sections.items():
        lines.append(f"[{name}]")
        lines.append(json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2))
    warnings = payload["warnings"]
    if warnings:
        lines.append("[warnings]")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)
