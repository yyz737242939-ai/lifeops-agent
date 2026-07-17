"""Request-local TraceContext, recording protocols, and compatibility telemetry."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Mapping, Protocol

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.common.validation import require_non_empty_string
from app.observability.logger import TraceSink
from app.observability.trace_models import (
    AnnotationRecord,
    ArtifactReference,
    FrozenMetadata,
    SpanEventRecord,
    SpanLinkRecord,
    SpanRecord,
    TraceRecord,
    TraceRecordItem,
)
from app.observability.trace_vocabulary import (
    AnnotationStatus,
    LifeOpsSpanKind,
    SpanLinkType,
    TraceSource,
    TraceStatus,
)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    current_span_id: str
    run_id: str
    session_id: str
    turn_id: str

    def __post_init__(self) -> None:
        for name in ("trace_id", "current_span_id", "run_id", "session_id", "turn_id"):
            require_non_empty_string(getattr(self, name), name)


@dataclass(frozen=True)
class StartSpanInput:
    name: str
    lifeops_span_kind: LifeOpsSpanKind
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty_string(self.name, "name")
        if not isinstance(self.lifeops_span_kind, LifeOpsSpanKind):
            raise ValueError("lifeops_span_kind must be a LifeOpsSpanKind value.")


@dataclass(frozen=True)
class SpanHandle:
    context: TraceContext
    parent_span_id: str | None
    name: str
    lifeops_span_kind: LifeOpsSpanKind
    started_at: str
    attributes: FrozenMetadata


@dataclass(frozen=True)
class SpanEventInput:
    name: str
    level: str = "info"
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty_string(self.name, "name")
        require_non_empty_string(self.level, "level")


@dataclass(frozen=True)
class SpanLinkInput:
    target_trace_id: str
    link_type: SpanLinkType
    target_span_id: str | None = None
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty_string(self.target_trace_id, "target_trace_id")
        if self.target_span_id is not None:
            require_non_empty_string(self.target_span_id, "target_span_id")
        if not isinstance(self.link_type, SpanLinkType):
            raise ValueError("link_type must be a SpanLinkType value.")


@dataclass(frozen=True)
class EndSpanInput:
    handle: SpanHandle
    status: TraceStatus = TraceStatus.OK
    error_code: str | None = None
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.handle, SpanHandle):
            raise ValueError("handle must be a SpanHandle.")
        if not isinstance(self.status, TraceStatus):
            raise ValueError("status must be a TraceStatus value.")
        if self.error_code is not None:
            require_non_empty_string(self.error_code, "error_code")
        if not isinstance(self.attributes, Mapping):
            raise ValueError("attributes must be a mapping.")


class SpanRecorder(Protocol):
    @property
    def trace_context(self) -> TraceContext: ...

    def start_span(self, span_input: StartSpanInput) -> SpanHandle: ...

    def add_event(self, event: SpanEventInput) -> None: ...

    def add_link(self, link: SpanLinkInput) -> None: ...

    def add_artifact_reference(self, artifact: ArtifactReference) -> None: ...

    def end_span(self, span_input: EndSpanInput) -> None: ...


class TraceExporter(Protocol):
    def export(self, records: tuple[TraceRecordItem, ...]) -> None: ...


class AnnotationSink(Protocol):
    def record(self, annotation: AnnotationRecord) -> None: ...


class RequestTelemetry(TraceSink, SpanRecorder):
    """Composite legacy event sink and request-local span recorder."""

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str,
        turn_id: str,
        legacy_sink: TraceSink,
        exporter: TraceExporter | None = None,
        annotation_sink: AnnotationSink | None = None,
        source: TraceSource = TraceSource.INTERACTIVE,
    ) -> None:
        self._legacy_sink = legacy_sink
        self._exporter = exporter
        self._annotation_sink = annotation_sink
        self._source = source
        self._started_at = utc_now_iso()
        self._trace_id = new_id("trace")
        root_span_id = new_id("span")
        self._root_span_id = root_span_id
        root_context = TraceContext(
            trace_id=self._trace_id,
            current_span_id=root_span_id,
            run_id=run_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        self._stack = [
            SpanHandle(
                context=root_context,
                parent_span_id=None,
                name="runtime.handle",
                lifeops_span_kind=LifeOpsSpanKind.RUNTIME,
                started_at=self._started_at,
                attributes=FrozenMetadata({"lifeops.runtime.run_id": run_id}),
            )
        ]
        self._sequences: dict[str, int] = {}
        self._finished = False
        self._logger = logging.getLogger("lifeops.observability")

    @property
    def trace_context(self) -> TraceContext:
        return self._stack[-1].context

    def append(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        try:
            self._legacy_sink.append(event_type, payload)
        except Exception:
            self._logger.error("legacy event export failed")

    def start_span(self, span_input: StartSpanInput) -> SpanHandle:
        if self._finished:
            raise RuntimeError("request telemetry is already finished.")
        parent = self._stack[-1]
        context = TraceContext(
            trace_id=parent.context.trace_id,
            current_span_id=new_id("span"),
            run_id=parent.context.run_id,
            session_id=parent.context.session_id,
            turn_id=parent.context.turn_id,
        )
        validated = SpanRecord(
            trace_id=context.trace_id,
            span_id=context.current_span_id,
            parent_span_id=parent.context.current_span_id,
            name=span_input.name,
            lifeops_span_kind=span_input.lifeops_span_kind,
            started_at=utc_now_iso(),
            attributes=span_input.attributes,
        )
        handle = SpanHandle(
            context=context,
            parent_span_id=validated.parent_span_id,
            name=validated.name,
            lifeops_span_kind=validated.lifeops_span_kind,
            started_at=validated.started_at,
            attributes=validated.attributes,
        )
        self._stack.append(handle)
        return handle

    def add_event(self, event: SpanEventInput) -> None:
        context = self.trace_context
        sequence = self._sequences.get(context.current_span_id, 0) + 1
        self._sequences[context.current_span_id] = sequence
        self._safe_export(
            SpanEventRecord(
                event_id=new_id("spanevt"),
                trace_id=context.trace_id,
                span_id=context.current_span_id,
                sequence=sequence,
                name=event.name,
                timestamp=utc_now_iso(),
                level=event.level,
                attributes=event.attributes,
            )
        )

    def add_link(self, link: SpanLinkInput) -> None:
        context = self.trace_context
        self._safe_export(
            SpanLinkRecord(
                link_id=new_id("spanlink"),
                source_trace_id=context.trace_id,
                source_span_id=context.current_span_id,
                target_trace_id=link.target_trace_id,
                target_span_id=link.target_span_id,
                link_type=link.link_type,
                attributes=link.attributes,
            )
        )

    def add_artifact_reference(self, artifact: ArtifactReference) -> None:
        context = self.trace_context
        if artifact.trace_id != context.trace_id:
            raise ValueError("artifact trace_id must match the request trace.")
        self._safe_export(artifact)

    def record_annotation(self, annotation: AnnotationRecord) -> None:
        if self._annotation_sink is None:
            return
        try:
            self._annotation_sink.record(annotation)
        except Exception:
            self._logger.error("annotation export failed")

    def end_span(self, span_input: EndSpanInput) -> None:
        if len(self._stack) == 1:
            raise ValueError("root span must be ended with finish().")
        if self._stack[-1] != span_input.handle:
            raise ValueError("spans must end in stack order.")
        handle = self._stack.pop()
        self._safe_export(
            self._span_record(
                handle,
                span_input.status,
                span_input.error_code,
                attributes=span_input.attributes,
            )
        )

    def finish(
        self,
        *,
        status: TraceStatus,
        error_code: str | None = None,
    ) -> None:
        if self._finished:
            return
        while len(self._stack) > 1:
            leaked = self._stack.pop()
            self._safe_export(
                self._span_record(leaked, TraceStatus.ERROR, "trace_span_incomplete")
            )
        root = self._stack.pop()
        ended_at = utc_now_iso()
        self._safe_export(self._span_record(root, status, error_code, ended_at=ended_at))
        self._safe_export(
            TraceRecord(
                trace_id=self._trace_id,
                session_id=root.context.session_id,
                turn_id=root.context.turn_id,
                run_id=root.context.run_id,
                root_span_id=self._root_span_id,
                source=self._source,
                started_at=self._started_at,
                ended_at=ended_at,
                status=status,
                error_code=error_code,
            )
        )
        self._finished = True

    def _span_record(
        self,
        handle: SpanHandle,
        status: TraceStatus,
        error_code: str | None,
        *,
        ended_at: str | None = None,
        attributes: Mapping[str, object] | None = None,
    ) -> SpanRecord:
        merged_attributes = dict(handle.attributes)
        merged_attributes.update(attributes or {})
        return SpanRecord(
            trace_id=handle.context.trace_id,
            span_id=handle.context.current_span_id,
            parent_span_id=handle.parent_span_id,
            name=handle.name,
            lifeops_span_kind=handle.lifeops_span_kind,
            started_at=handle.started_at,
            ended_at=ended_at or utc_now_iso(),
            status=status,
            error_code=error_code,
            attributes=merged_attributes,
        )

    def _safe_export(self, *records: TraceRecordItem) -> None:
        if self._exporter is None:
            return
        try:
            self._exporter.export(tuple(records))
        except Exception:
            self._logger.error("trace export failed")


class SpanScope:
    """Mutable context-manager outcome; emitted records remain immutable."""

    def __init__(self, handle: SpanHandle | None) -> None:
        self.handle = handle
        self.status = TraceStatus.OK
        self.error_code: str | None = None
        self.attributes: dict[str, object] = {}

    def fail(self, error_code: str) -> None:
        require_non_empty_string(error_code, "error_code")
        self.status = TraceStatus.ERROR
        self.error_code = error_code

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        if not isinstance(attributes, Mapping):
            raise ValueError("attributes must be a mapping.")
        self.attributes.update(attributes)


@contextmanager
def optional_span(
    trace: TraceSink | None,
    *,
    name: str,
    kind: LifeOpsSpanKind,
    attributes: Mapping[str, object] | None = None,
) -> Iterator[SpanScope]:
    """Record a current span when the supplied legacy sink supports it."""

    start = getattr(trace, "start_span", None)
    end = getattr(trace, "end_span", None)
    if not callable(start) or not callable(end):
        yield SpanScope(None)
        return
    try:
        handle = start(StartSpanInput(name, kind, attributes or {}))
    except Exception:
        yield SpanScope(None)
        return
    scope = SpanScope(handle)
    try:
        yield scope
    except Exception:
        try:
            end(EndSpanInput(handle, TraceStatus.ERROR, "operation_failed"))
        except Exception:
            pass
        raise
    else:
        try:
            end(EndSpanInput(handle, scope.status, scope.error_code, scope.attributes))
        except Exception:
            pass


def add_span_event(
    trace: TraceSink | None,
    name: str,
    attributes: Mapping[str, object] | None = None,
) -> None:
    add = getattr(trace, "add_event", None)
    if callable(add):
        add(SpanEventInput(name=name, attributes=attributes or {}))


def add_span_link(trace: TraceSink | None, link: SpanLinkInput) -> None:
    add = getattr(trace, "add_link", None)
    if callable(add):
        add(link)
