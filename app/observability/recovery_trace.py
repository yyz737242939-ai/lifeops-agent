"""Shared trace projections for downstream ExecutionFeedback and Recovery."""

from __future__ import annotations

from app.common.ids import new_id
from app.observability.logger import TraceSink
from app.observability.telemetry import SpanLinkInput, add_span_link
from app.observability.trace_models import ArtifactReference
from app.observability.trace_vocabulary import ArtifactSensitivity, SpanLinkType


def record_execution_feedback_reference(
    trace: TraceSink | None,
    *,
    safe_reference: str,
    content_hash: str | None = None,
    sensitivity: ArtifactSensitivity = ArtifactSensitivity.INTERNAL,
) -> ArtifactReference | None:
    """Project already-finalized feedback without owning or creating that fact."""

    add = getattr(trace, "add_artifact_reference", None)
    context = getattr(trace, "trace_context", None)
    if not callable(add) or context is None:
        return None
    try:
        artifact = ArtifactReference(
            artifact_id=new_id("artifact"),
            trace_id=context.trace_id,
            span_id=context.current_span_id,
            artifact_type="execution_feedback",
            storage_kind="safe_reference",
            safe_reference=safe_reference,
            content_hash=content_hash,
            sensitivity=sensitivity,
        )
        add(artifact)
        return artifact
    except Exception:
        return None


def record_recovery_context_reference(
    trace: TraceSink | None,
    *,
    safe_reference: str,
    sensitivity: ArtifactSensitivity = ArtifactSensitivity.INTERNAL,
) -> ArtifactReference | None:
    """Project a safe reference to request-local RecoveryContext."""

    add = getattr(trace, "add_artifact_reference", None)
    context = getattr(trace, "trace_context", None)
    if not callable(add) or context is None:
        return None
    try:
        artifact = ArtifactReference(
            artifact_id=new_id("artifact"),
            trace_id=context.trace_id,
            span_id=context.current_span_id,
            artifact_type="recovery_context",
            storage_kind="request_local_reference",
            safe_reference=safe_reference,
            sensitivity=sensitivity,
        )
        add(artifact)
        return artifact
    except Exception:
        return None


def record_recovery_of(
    trace: TraceSink | None,
    *,
    source_trace_id: str,
    source_span_id: str | None = None,
) -> None:
    """Link a read-only Recovery trace to its source execution trace."""

    try:
        add_span_link(
            trace,
            SpanLinkInput(
                target_trace_id=source_trace_id,
                target_span_id=source_span_id,
                link_type=SpanLinkType.RECOVERY_OF,
            ),
        )
    except Exception:
        return
