"""Rebuildable SQLite query index derived from canonical trace files."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.common.serialization import to_json
from app.observability.trace_models import (
    AnnotationRecord,
    ArtifactReference,
    SpanEventRecord,
    SpanLinkRecord,
    SpanRecord,
    TraceRecord,
)
from app.observability.trace_serialization import deserialize_record


@dataclass(frozen=True)
class IndexReport:
    session_dir: str
    indexed_records: int
    indexed_annotations: int
    corrupt_files: tuple[str, ...] = ()


class TraceIndexBuilder:
    """Build an optional derived index outside Runtime transactions."""

    def __init__(self, index_path: str | Path) -> None:
        self.index_path = Path(index_path)

    def index_session(self, session_dir: Path) -> IndexReport:
        session_dir = session_dir.resolve()
        trace_path = session_dir / "traces.jsonl"
        annotation_path = session_dir / "annotations.jsonl"
        records, trace_corrupt = _read_file(trace_path)
        annotations, annotation_corrupt = _read_file(annotation_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.index_path)
        try:
            _create_schema(conn)
            session_key = str(session_dir)
            for table in (
                "traces", "spans", "span_events", "span_links",
                "artifact_references", "annotations",
            ):
                conn.execute(f"DELETE FROM {table} WHERE session_dir = ?", (session_key,))
            conn.execute("DELETE FROM indexed_files WHERE session_dir = ?", (session_key,))
            indexed_records = 0
            indexed_annotations = 0
            for line_number, entry in records:
                record = deserialize_record(entry)
                if isinstance(record, AnnotationRecord):
                    raise ValueError("annotations must be stored in annotations.jsonl.")
                _insert_record(conn, session_key, line_number, entry, record)
                indexed_records += 1
            for line_number, entry in annotations:
                record = deserialize_record(entry)
                if not isinstance(record, AnnotationRecord):
                    raise ValueError("annotations.jsonl must contain annotations.")
                conn.execute(
                    """INSERT INTO annotations
                       (annotation_id, trace_id, span_id, kind, status, session_dir,
                        line_number, payload_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.annotation_id, record.target_trace_id,
                        record.target_span_id, record.annotation_kind.value,
                        record.status.value, session_key, line_number, to_json(entry),
                    ),
                )
                indexed_annotations += 1
            for path, corrupt in (
                (trace_path, trace_corrupt),
                (annotation_path, annotation_corrupt),
            ):
                conn.execute(
                    """INSERT INTO indexed_files
                       (path, session_dir, size_bytes, modified_ns, corrupt)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        str(path.resolve()), session_key,
                        path.stat().st_size if path.exists() else 0,
                        path.stat().st_mtime_ns if path.exists() else 0,
                        int(corrupt),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        corrupt_files = tuple(
            str(path)
            for path, corrupt in (
                (trace_path, trace_corrupt),
                (annotation_path, annotation_corrupt),
            )
            if corrupt
        )
        return IndexReport(
            str(session_dir), indexed_records, indexed_annotations, corrupt_files
        )


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS traces (
            trace_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_id TEXT NOT NULL,
            status TEXT NOT NULL, session_dir TEXT NOT NULL, line_number INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trace_run ON traces(run_id);
        CREATE TABLE IF NOT EXISTS spans (
            span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, parent_span_id TEXT,
            kind TEXT NOT NULL, plan_id TEXT, session_dir TEXT NOT NULL,
            line_number INTEGER NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_span_trace ON spans(trace_id);
        CREATE INDEX IF NOT EXISTS idx_span_plan ON spans(plan_id);
        CREATE TABLE IF NOT EXISTS span_events (
            event_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, span_id TEXT NOT NULL,
            session_dir TEXT NOT NULL, line_number INTEGER NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS span_links (
            link_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, span_id TEXT NOT NULL,
            target_trace_id TEXT NOT NULL, link_type TEXT NOT NULL,
            session_dir TEXT NOT NULL, line_number INTEGER NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifact_references (
            artifact_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, span_id TEXT,
            sensitivity TEXT NOT NULL, session_dir TEXT NOT NULL,
            line_number INTEGER NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS annotations (
            annotation_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, span_id TEXT,
            kind TEXT NOT NULL, status TEXT NOT NULL, session_dir TEXT NOT NULL,
            line_number INTEGER NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS indexed_files (
            path TEXT PRIMARY KEY, session_dir TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL, corrupt INTEGER NOT NULL
        );
        """
    )


def _insert_record(
    conn: sqlite3.Connection,
    session_dir: str,
    line_number: int,
    entry: dict[str, object],
    record: object,
) -> None:
    payload = to_json(entry)
    if isinstance(record, TraceRecord):
        conn.execute(
            "INSERT INTO traces VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.trace_id, record.run_id, record.session_id,
                record.status.value, session_dir, line_number, payload,
            ),
        )
    elif isinstance(record, SpanRecord):
        conn.execute(
            "INSERT INTO spans VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.span_id, record.trace_id, record.parent_span_id,
                record.lifeops_span_kind.value, record.attributes.get("lifeops.plan.id"),
                session_dir, line_number, payload,
            ),
        )
    elif isinstance(record, SpanEventRecord):
        conn.execute(
            "INSERT INTO span_events VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.event_id, record.trace_id, record.span_id,
                session_dir, line_number, payload,
            ),
        )
    elif isinstance(record, SpanLinkRecord):
        conn.execute(
            "INSERT INTO span_links VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.link_id, record.source_trace_id, record.source_span_id,
                record.target_trace_id, record.link_type.value,
                session_dir, line_number, payload,
            ),
        )
    elif isinstance(record, ArtifactReference):
        conn.execute(
            "INSERT INTO artifact_references VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.artifact_id, record.trace_id, record.span_id,
                record.sensitivity.value, session_dir, line_number, payload,
            ),
        )
    else:
        raise ValueError("unsupported trace record.")


def _read_file(path: Path) -> tuple[list[tuple[int, dict[str, object]]], bool]:
    if not path.exists():
        return [], False
    rows: list[tuple[int, dict[str, object]]] = []
    corrupt = False
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
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
            rows.append((line_number, value))
    return rows, corrupt
