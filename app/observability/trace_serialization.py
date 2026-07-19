"""Serialization boundary for canonical LifeOps Trace Contract records."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from app.observability.trace_models import (
    AnnotationRecord,
    ArtifactReference,
    SpanEventRecord,
    SpanLinkRecord,
    SpanRecord,
    TraceRecord,
    TraceRecordItem,
)
from app.observability.trace_vocabulary import (
    AnnotationKind,
    AnnotationProducer,
    AnnotationSeverity,
    AnnotationStatus,
    ArtifactSensitivity,
    LifeOpsSpanKind,
    SpanLinkType,
    TraceSource,
    TraceStatus,
)

_RECORD_TYPES = {
    "trace": TraceRecord,
    "span": SpanRecord,
    "span_event": SpanEventRecord,
    "span_link": SpanLinkRecord,
    "artifact_reference": ArtifactReference,
    "annotation": AnnotationRecord,
}

_ENUM_FIELDS = {
    TraceRecord: {"source": TraceSource, "status": TraceStatus},
    SpanRecord: {
        "lifeops_span_kind": LifeOpsSpanKind,
        "status": TraceStatus,
    },
    SpanLinkRecord: {"link_type": SpanLinkType},
    ArtifactReference: {"sensitivity": ArtifactSensitivity},
    AnnotationRecord: {
        "annotation_kind": AnnotationKind,
        "producer": AnnotationProducer,
        "status": AnnotationStatus,
        "severity": AnnotationSeverity,
    },
}


def deserialize_record(
    entry: dict[str, Any],
) -> TraceRecordItem | AnnotationRecord:
    """Validate one known v1 JSON envelope and ignore additive optional fields."""

    if not isinstance(entry, dict):
        raise ValueError("trace record must be a JSON object.")
    record_type = entry.get("record_type")
    model_type = _RECORD_TYPES.get(record_type)
    if model_type is None:
        raise ValueError("trace record_type is unknown.")
    if entry.get("schema_version") != 1:
        raise ValueError("trace schema_version is unknown.")
    allowed = {item.name for item in fields(model_type)}
    values = {key: value for key, value in entry.items() if key in allowed}
    for field_name, enum_type in _ENUM_FIELDS.get(model_type, {}).items():
        value = values.get(field_name)
        if value is not None:
            values[field_name] = enum_type(value)
    return model_type(**values)
