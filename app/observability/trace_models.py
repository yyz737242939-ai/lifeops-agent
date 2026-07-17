"""Immutable, framework-independent models for LifeOps Trace Contract v1."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable, Mapping, TypeAlias

from app.common.time import utc_now_iso
from app.common.validation import require_non_empty_string
from app.observability.trace_vocabulary import (
    TRACE_SCHEMA_VERSION,
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

MetadataScalar: TypeAlias = str | bool | int | float
MetadataValue: TypeAlias = MetadataScalar | tuple[MetadataScalar, ...]


class FrozenMetadata(dict[str, MetadataValue]):
    """A JSON-object-compatible mapping that rejects mutation."""

    def __init__(
        self,
        values: Mapping[str, MetadataValue]
        | Iterable[tuple[str, MetadataValue]] = (),
    ) -> None:
        dict.__init__(self, values)

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("trace metadata is immutable.")

    __delitem__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

_STABLE_TOKEN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.:/-]*$")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_SENSITIVE_KEY_PARTS = (
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
)
_SAFE_METADATA_KEYS = frozenset(
    {
        "llm.usage.input_tokens",
        "llm.usage.output_tokens",
        "llm.usage.total_tokens",
    }
)


def _required_text(value: str, name: str) -> None:
    require_non_empty_string(value, name)


def _optional_text(value: str | None, name: str) -> None:
    if value is not None:
        _required_text(value, name)


def _stable_token(value: str, name: str) -> None:
    _required_text(value, name)
    if _STABLE_TOKEN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a stable token.")


def _enum(value: object, enum_type: type, name: str) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(f"{name} must be a {enum_type.__name__} value.")


def _timestamp(value: str, name: str) -> datetime:
    _required_text(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{name} must be UTC and timezone-aware.")
    return parsed


def _schema_version(value: int) -> None:
    if value != TRACE_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {TRACE_SCHEMA_VERSION}.")


def _metadata(value: Mapping[str, object], name: str) -> FrozenMetadata:
    if isinstance(value, Mapping):
        items = tuple(value.items())
    else:
        raise ValueError(f"{name} must be a metadata mapping.")

    normalized: list[tuple[str, MetadataValue]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError(f"{name} must contain key/value pairs.")
        key, raw = item
        if not isinstance(key, str) or _STABLE_TOKEN.fullmatch(key) is None:
            raise ValueError(f"{name} keys must be stable tokens.")
        lowered = key.lower()
        if key not in _SAFE_METADATA_KEYS and any(
            part in lowered for part in _SENSITIVE_KEY_PARTS
        ):
            raise ValueError(f"{name} contains a forbidden sensitive key.")
        if key in seen:
            raise ValueError(f"{name} keys must be unique.")
        seen.add(key)
        normalized.append((key, _metadata_value(raw, name)))
    return FrozenMetadata(sorted(normalized, key=lambda pair: pair[0]))


def freeze_metadata(value: Mapping[str, object], name: str = "attributes") -> FrozenMetadata:
    """Return validated immutable low-level metadata for shared read models."""

    return _metadata(value, name)


def _metadata_value(value: object, name: str) -> MetadataValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} values must be finite.")
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (tuple, list)):
        result = tuple(value)
        if not result or any(not isinstance(item, (str, bool, int, float)) for item in result):
            raise ValueError(f"{name} arrays must contain metadata scalars.")
        if any(isinstance(item, float) and not math.isfinite(item) for item in result):
            raise ValueError(f"{name} values must be finite.")
        return result
    raise ValueError(f"{name} values must be JSON metadata scalars or scalar arrays.")


@dataclass(frozen=True)
class TraceRecord:
    trace_id: str
    session_id: str
    turn_id: str
    run_id: str
    root_span_id: str
    source: TraceSource
    started_at: str
    ended_at: str | None = None
    status: TraceStatus = TraceStatus.UNSET
    error_code: str | None = None
    resource_attributes: FrozenMetadata | Mapping[str, object] = field(default_factory=FrozenMetadata)
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema_version(self.schema_version)
        for name in ("trace_id", "session_id", "turn_id", "run_id", "root_span_id"):
            _required_text(getattr(self, name), name)
        _enum(self.source, TraceSource, "source")
        _enum(self.status, TraceStatus, "status")
        started = _timestamp(self.started_at, "started_at")
        if self.ended_at is not None and _timestamp(self.ended_at, "ended_at") < started:
            raise ValueError("ended_at must not precede started_at.")
        _optional_text(self.error_code, "error_code")
        object.__setattr__(self, "resource_attributes", _metadata(self.resource_attributes, "resource_attributes"))


@dataclass(frozen=True)
class SpanRecord:
    trace_id: str
    span_id: str
    name: str
    lifeops_span_kind: LifeOpsSpanKind
    started_at: str
    parent_span_id: str | None = None
    ended_at: str | None = None
    status: TraceStatus = TraceStatus.UNSET
    error_code: str | None = None
    attributes: FrozenMetadata | Mapping[str, object] = field(default_factory=FrozenMetadata)
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema_version(self.schema_version)
        for name in ("trace_id", "span_id", "name"):
            _required_text(getattr(self, name), name)
        _optional_text(self.parent_span_id, "parent_span_id")
        if self.parent_span_id == self.span_id:
            raise ValueError("parent_span_id must differ from span_id.")
        _enum(self.lifeops_span_kind, LifeOpsSpanKind, "lifeops_span_kind")
        _enum(self.status, TraceStatus, "status")
        started = _timestamp(self.started_at, "started_at")
        if self.ended_at is not None and _timestamp(self.ended_at, "ended_at") < started:
            raise ValueError("ended_at must not precede started_at.")
        _optional_text(self.error_code, "error_code")
        object.__setattr__(self, "attributes", _metadata(self.attributes, "attributes"))


@dataclass(frozen=True)
class SpanEventRecord:
    event_id: str
    trace_id: str
    span_id: str
    sequence: int
    name: str
    timestamp: str
    level: str
    attributes: FrozenMetadata | Mapping[str, object] = field(default_factory=FrozenMetadata)
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema_version(self.schema_version)
        for name in ("event_id", "trace_id", "span_id", "name"):
            _required_text(getattr(self, name), name)
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer.")
        _timestamp(self.timestamp, "timestamp")
        _stable_token(self.level, "level")
        object.__setattr__(self, "attributes", _metadata(self.attributes, "attributes"))


@dataclass(frozen=True)
class SpanLinkRecord:
    link_id: str
    source_trace_id: str
    source_span_id: str
    target_trace_id: str
    link_type: SpanLinkType
    target_span_id: str | None = None
    attributes: FrozenMetadata | Mapping[str, object] = field(default_factory=FrozenMetadata)
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema_version(self.schema_version)
        for name in ("link_id", "source_trace_id", "source_span_id", "target_trace_id"):
            _required_text(getattr(self, name), name)
        _optional_text(self.target_span_id, "target_span_id")
        if self.source_trace_id == self.target_trace_id and self.source_span_id == self.target_span_id:
            raise ValueError("a span link cannot target its source span.")
        _enum(self.link_type, SpanLinkType, "link_type")
        object.__setattr__(self, "attributes", _metadata(self.attributes, "attributes"))


@dataclass(frozen=True)
class ArtifactReference:
    artifact_id: str
    trace_id: str
    artifact_type: str
    storage_kind: str
    safe_reference: str
    sensitivity: ArtifactSensitivity
    created_at: str = field(default_factory=utc_now_iso)
    span_id: str | None = None
    content_hash: str | None = None
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema_version(self.schema_version)
        for name in ("artifact_id", "trace_id", "safe_reference"):
            _required_text(getattr(self, name), name)
        _stable_token(self.artifact_type, "artifact_type")
        _stable_token(self.storage_kind, "storage_kind")
        _optional_text(self.span_id, "span_id")
        if self.content_hash is not None and _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must be a SHA-256 digest.")
        _enum(self.sensitivity, ArtifactSensitivity, "sensitivity")
        _timestamp(self.created_at, "created_at")


@dataclass(frozen=True)
class AnnotationRecord:
    annotation_id: str
    target_trace_id: str
    annotation_kind: AnnotationKind
    producer: AnnotationProducer
    status: AnnotationStatus
    created_at: str = field(default_factory=utc_now_iso)
    target_span_id: str | None = None
    evaluator_id: str | None = None
    producer_version: str | None = None
    source_fingerprint: str | None = None
    eval_run_id: str | None = None
    eval_suite_id: str | None = None
    eval_case_id: str | None = None
    severity: AnnotationSeverity | None = None
    score: float | None = None
    label: str | None = None
    reason_code: str | None = None
    safe_explanation: str | None = None
    schema_version: int = TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema_version(self.schema_version)
        for name in ("annotation_id", "target_trace_id"):
            _required_text(getattr(self, name), name)
        for name in (
            "target_span_id", "evaluator_id", "producer_version", "source_fingerprint",
            "eval_run_id", "eval_suite_id", "eval_case_id", "label", "reason_code",
            "safe_explanation",
        ):
            _optional_text(getattr(self, name), name)
        _enum(self.annotation_kind, AnnotationKind, "annotation_kind")
        _enum(self.producer, AnnotationProducer, "producer")
        _enum(self.status, AnnotationStatus, "status")
        if self.severity is not None:
            _enum(self.severity, AnnotationSeverity, "severity")
        lineage = (self.eval_run_id, self.eval_suite_id, self.eval_case_id)
        if any(value is not None for value in lineage) and not all(value is not None for value in lineage):
            raise ValueError("eval lineage must be entirely present or absent.")
        if self.annotation_kind is AnnotationKind.EVALUATION and (
            self.evaluator_id is None or not all(value is not None for value in lineage)
        ):
            raise ValueError("evaluation annotations require evaluator_id and complete eval lineage.")
        if self.score is not None and (
            isinstance(self.score, bool) or not isinstance(self.score, (int, float)) or not math.isfinite(self.score)
        ):
            raise ValueError("score must be a finite number when provided.")
        _timestamp(self.created_at, "created_at")


TraceRecordItem: TypeAlias = (
    TraceRecord | SpanRecord | SpanEventRecord | SpanLinkRecord | ArtifactReference
)
