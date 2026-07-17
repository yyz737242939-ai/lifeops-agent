"""Canonical trace store, integrity validation, and TraceGraph reconstruction."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from app.observability.trace_models import (
    AnnotationRecord,
    ArtifactReference,
    SpanEventRecord,
    SpanLinkRecord,
    SpanRecord,
    TraceRecord,
    TraceRecordItem,
)
from app.observability.trace_serialization import deserialize_record


class TraceReadError(ValueError):
    """Fail-closed error for an unavailable or invalid canonical trace."""


@dataclass(frozen=True)
class TraceGraph:
    trace: TraceRecord
    root_span: SpanRecord
    spans_by_id: Mapping[str, SpanRecord]
    children_by_parent: Mapping[str, tuple[SpanRecord, ...]]
    events: tuple[SpanEventRecord, ...]
    links: tuple[SpanLinkRecord, ...]
    artifacts: tuple[ArtifactReference, ...]
    annotations: tuple[AnnotationRecord, ...]
    integrity_warnings: tuple[str, ...] = ()


class FileTraceStore:
    """Locate canonical records, optionally using a disposable query index."""

    def __init__(
        self,
        log_root: str | Path,
        *,
        index_path: str | Path | None = None,
    ) -> None:
        self.log_root = Path(log_root)
        self.index_path = Path(index_path) if index_path is not None else None
        self._warnings: dict[str, tuple[str, ...]] = {}

    def load_records(self, trace_id: str) -> tuple[TraceRecordItem, ...]:
        indexed = self._load_index_records(trace_id)
        if indexed:
            self._warnings[trace_id] = ()
            return indexed
        records, warnings = self._scan_records(trace_id)
        self._warnings[trace_id] = warnings
        return records

    def load_annotations(self, trace_id: str) -> tuple[AnnotationRecord, ...]:
        indexed = self._load_index_annotations(trace_id)
        if indexed:
            return indexed
        annotations: list[AnnotationRecord] = []
        for path in sorted(self.log_root.rglob("annotations.jsonl")):
            entries, _corrupt = _read_jsonl(path)
            for entry in entries:
                record = deserialize_record(entry)
                if isinstance(record, AnnotationRecord) and record.target_trace_id == trace_id:
                    annotations.append(record)
        return tuple(annotations)

    def load_warnings(self, trace_id: str) -> tuple[str, ...]:
        return self._warnings.get(trace_id, ())

    def find_trace_ids_by_run(self, run_id: str) -> tuple[str, ...]:
        indexed = self._index_values(
            "SELECT trace_id FROM traces WHERE run_id = ? ORDER BY trace_id",
            (run_id,),
        )
        if indexed:
            return indexed
        found: set[str] = set()
        for path in sorted(self.log_root.rglob("traces.jsonl")):
            entries, _corrupt = _read_jsonl(path)
            for entry in entries:
                record = deserialize_record(entry)
                if isinstance(record, TraceRecord) and record.run_id == run_id:
                    found.add(record.trace_id)
        return tuple(sorted(found))

    def find_trace_ids_by_plan(self, plan_id: str) -> tuple[str, ...]:
        indexed = self._index_values(
            "SELECT DISTINCT trace_id FROM spans WHERE plan_id = ? ORDER BY trace_id",
            (plan_id,),
        )
        if indexed:
            return indexed
        found: set[str] = set()
        for path in sorted(self.log_root.rglob("traces.jsonl")):
            entries, _corrupt = _read_jsonl(path)
            for entry in entries:
                record = deserialize_record(entry)
                if (
                    isinstance(record, SpanRecord)
                    and record.attributes.get("lifeops.plan.id") == plan_id
                ):
                    found.add(record.trace_id)
        return tuple(sorted(found))

    def find_plan_preview_trace_id(self, plan_id: str) -> str | None:
        """Resolve the one canonical preview trace for a durable Plan identity."""

        matches: set[str] = set()
        for trace_id in self.find_trace_ids_by_plan(plan_id):
            for record in self.load_records(trace_id):
                if (
                    isinstance(record, SpanRecord)
                    and record.name == "planning.route"
                    and record.attributes.get("lifeops.plan.id") == plan_id
                ):
                    matches.add(trace_id)
        if len(matches) > 1:
            raise TraceReadError(f"multiple preview traces for plan:{plan_id}")
        return next(iter(matches), None)

    def _scan_records(
        self, trace_id: str
    ) -> tuple[tuple[TraceRecordItem, ...], tuple[str, ...]]:
        records: list[TraceRecordItem] = []
        warnings: list[str] = []
        for path in sorted(self.log_root.rglob("traces.jsonl")):
            entries, corrupt = _read_jsonl(path)
            if corrupt:
                warnings.append(f"source_corrupt:{path}")
            for entry in entries:
                record = deserialize_record(entry)
                if _record_trace_id(record) == trace_id:
                    records.append(record)
        return tuple(records), tuple(warnings)

    def _load_index_records(self, trace_id: str) -> tuple[TraceRecordItem, ...]:
        rows = self._index_payloads(
            (
                ("traces", "trace_id"),
                ("spans", "trace_id"),
                ("span_events", "trace_id"),
                ("span_links", "trace_id"),
                ("artifact_references", "trace_id"),
            ),
            trace_id,
        )
        records: list[TraceRecordItem] = []
        for payload in rows:
            record = deserialize_record(json.loads(payload))
            if isinstance(record, AnnotationRecord):
                raise TraceReadError("trace index contains an annotation in trace records.")
            records.append(record)
        return tuple(records)

    def _load_index_annotations(self, trace_id: str) -> tuple[AnnotationRecord, ...]:
        if not self._index_is_fresh():
            return ()
        try:
            conn = sqlite3.connect(f"file:{self.index_path.resolve()}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT payload_json FROM annotations WHERE trace_id = ? ORDER BY line_number",
                    (trace_id,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return ()
        result: list[AnnotationRecord] = []
        for (payload,) in rows:
            record = deserialize_record(json.loads(payload))
            if not isinstance(record, AnnotationRecord):
                raise TraceReadError("annotation index contains a trace record.")
            result.append(record)
        return tuple(result)

    def _index_payloads(
        self,
        tables: tuple[tuple[str, str], ...],
        identity: str,
    ) -> tuple[str, ...]:
        if not self._index_is_fresh():
            return ()
        try:
            conn = sqlite3.connect(f"file:{self.index_path.resolve()}?mode=ro", uri=True)
            try:
                payloads: list[str] = []
                for table, column in tables:
                    rows = conn.execute(
                        f"SELECT payload_json FROM {table} WHERE {column} = ? "
                        "ORDER BY line_number",
                        (identity,),
                    ).fetchall()
                    payloads.extend(row[0] for row in rows)
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return ()
        return tuple(payloads)

    def _index_values(self, sql: str, parameters: tuple[str, ...]) -> tuple[str, ...]:
        if not self._index_is_fresh():
            return ()
        try:
            conn = sqlite3.connect(f"file:{self.index_path.resolve()}?mode=ro", uri=True)
            try:
                rows = conn.execute(sql, parameters).fetchall()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return ()
        return tuple(row[0] for row in rows)

    def _index_is_fresh(self) -> bool:
        if self.index_path is None or not self.index_path.exists():
            return False
        try:
            conn = sqlite3.connect(f"file:{self.index_path.resolve()}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT path, size_bytes, modified_ns, corrupt FROM indexed_files"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return False
        if not rows:
            return False
        for raw_path, size_bytes, modified_ns, corrupt in rows:
            path = Path(raw_path)
            if corrupt or not path.exists():
                return False
            stat = path.stat()
            if stat.st_size != size_bytes or stat.st_mtime_ns != modified_ns:
                return False
        return True


class TraceReader:
    """Validate canonical records and build the one shared telemetry graph."""

    def __init__(self, store: FileTraceStore) -> None:
        self._store = store

    def get_trace(self, trace_id: str) -> TraceGraph:
        records = self._store.load_records(trace_id)
        traces = _dedupe(records, TraceRecord, lambda item: item.trace_id)
        if len(traces) != 1:
            raise TraceReadError("trace must contain exactly one TraceRecord.")
        trace = traces[0]
        spans = _dedupe(records, SpanRecord, lambda item: item.span_id)
        spans_by_id = {span.span_id: span for span in spans}
        root = spans_by_id.get(trace.root_span_id)
        if root is None or root.parent_span_id is not None:
            raise TraceReadError("trace root span is missing or has a parent.")
        warnings = list(self._store.load_warnings(trace_id))
        children: dict[str, list[SpanRecord]] = {}
        for span in spans:
            if span.parent_span_id is None:
                if span.span_id != root.span_id:
                    warnings.append(f"unexpected_root:{span.span_id}")
                continue
            if span.parent_span_id not in spans_by_id:
                warnings.append(f"missing_parent:{span.span_id}:{span.parent_span_id}")
                continue
            children.setdefault(span.parent_span_id, []).append(span)
        _validate_cycles(spans_by_id)
        events = _dedupe(records, SpanEventRecord, lambda item: item.event_id)
        links = _dedupe(records, SpanLinkRecord, lambda item: item.link_id)
        artifacts = _dedupe(records, ArtifactReference, lambda item: item.artifact_id)
        for event in events:
            if event.span_id not in spans_by_id:
                warnings.append(f"missing_event_span:{event.event_id}:{event.span_id}")
        event_sequences: dict[tuple[str, int], str] = {}
        for event in events:
            key = (event.span_id, event.sequence)
            previous = event_sequences.get(key)
            if previous is not None and previous != event.event_id:
                warnings.append(
                    f"duplicate_event_sequence:{event.span_id}:{event.sequence}"
                )
            event_sequences[key] = event.event_id
        for link in links:
            if link.source_span_id not in spans_by_id:
                warnings.append(f"missing_link_source:{link.link_id}:{link.source_span_id}")
            if (
                link.target_trace_id == trace_id
                and link.target_span_id is not None
                and link.target_span_id not in spans_by_id
            ):
                warnings.append(f"missing_link_target:{link.link_id}:{link.target_span_id}")
        annotations = self._store.load_annotations(trace_id)
        for artifact in artifacts:
            if artifact.span_id is not None and artifact.span_id not in spans_by_id:
                warnings.append(
                    f"missing_artifact_span:{artifact.artifact_id}:{artifact.span_id}"
                )
        for annotation in annotations:
            if (
                annotation.target_span_id is not None
                and annotation.target_span_id not in spans_by_id
            ):
                warnings.append(
                    "missing_annotation_span:"
                    f"{annotation.annotation_id}:{annotation.target_span_id}"
                )
        return TraceGraph(
            trace=trace,
            root_span=root,
            spans_by_id=MappingProxyType(dict(sorted(spans_by_id.items()))),
            children_by_parent=MappingProxyType(
                {
                    parent: tuple(sorted(items, key=lambda item: (item.started_at, item.span_id)))
                    for parent, items in sorted(children.items())
                }
            ),
            events=tuple(sorted(events, key=lambda item: (item.timestamp, item.event_id))),
            links=tuple(sorted(links, key=lambda item: item.link_id)),
            artifacts=tuple(sorted(artifacts, key=lambda item: item.artifact_id)),
            annotations=tuple(sorted(annotations, key=lambda item: item.annotation_id)),
            integrity_warnings=tuple(sorted(set(warnings))),
        )

    def find_by_run(self, run_id: str) -> TraceGraph:
        trace_ids = self._store.find_trace_ids_by_run(run_id)
        if len(trace_ids) != 1:
            raise TraceReadError("run_id must resolve to exactly one trace.")
        return self.get_trace(trace_ids[0])

    def find_by_plan(self, plan_id: str) -> tuple[TraceGraph, ...]:
        return tuple(
            self.get_trace(trace_id)
            for trace_id in self._store.find_trace_ids_by_plan(plan_id)
        )


def _read_jsonl(path: Path) -> tuple[list[dict[str, object]], bool]:
    rows: list[dict[str, object]] = []
    corrupt = False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                corrupt = True
                break
            if not isinstance(value, dict):
                corrupt = True
                break
            rows.append(value)
    return rows, corrupt


def _record_trace_id(record: TraceRecordItem) -> str:
    if isinstance(record, SpanLinkRecord):
        return record.source_trace_id
    return record.trace_id


def _dedupe(records, expected_type, identity):
    unique = {}
    for record in records:
        if not isinstance(record, expected_type):
            continue
        key = identity(record)
        previous = unique.get(key)
        if previous is not None and previous != record:
            raise TraceReadError(f"conflicting duplicate identity:{key}")
        unique[key] = record
    return tuple(unique[key] for key in sorted(unique))


def _validate_cycles(spans_by_id: dict[str, SpanRecord]) -> None:
    for span in spans_by_id.values():
        seen: set[str] = set()
        current = span
        while current.parent_span_id is not None:
            if current.span_id in seen:
                raise TraceReadError("span parent cycle detected.")
            seen.add(current.span_id)
            parent = spans_by_id.get(current.parent_span_id)
            if parent is None:
                break
            current = parent
