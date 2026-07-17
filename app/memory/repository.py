"""SQLite metadata repository for committed long-term Memory versions."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Protocol

from app.memory.errors import MemoryErrorCode, MemoryRepositoryError
from app.memory.models import MemoryIndexRecord, MemoryStatus


class MemoryRepository(Protocol):
    def find_active_duplicate(self, content_hash: str) -> MemoryIndexRecord | None: ...

    def list_active_index(self) -> tuple[MemoryIndexRecord, ...]: ...

    def list_all_index(self) -> tuple[MemoryIndexRecord, ...]: ...

    def get_version(self, memory_id: str, version: int) -> MemoryIndexRecord: ...

    def insert_active(self, record: MemoryIndexRecord) -> None: ...

    def supersede_and_insert(
        self, expected_version: int, new_record: MemoryIndexRecord
    ) -> None: ...

    def archive(
        self, memory_id: str, expected_version: int, *, updated_at: str
    ) -> MemoryIndexRecord: ...

    def list_versions(self, memory_id: str) -> tuple[MemoryIndexRecord, ...]: ...

    def list_archived(self) -> tuple[MemoryIndexRecord, ...]: ...


class SqliteMemoryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def find_active_duplicate(self, content_hash: str) -> MemoryIndexRecord | None:
        row = self._fetchone(
            """SELECT * FROM memory_index
               WHERE status = 'active' AND content_hash = ?
               ORDER BY updated_at DESC, memory_id, version LIMIT 1""",
            (content_hash,),
        )
        return _record_from_row(row) if row is not None else None

    def list_active_index(self) -> tuple[MemoryIndexRecord, ...]:
        return self._fetch_records(
            """SELECT * FROM memory_index WHERE status = 'active'
               ORDER BY updated_at DESC, memory_id, version"""
        )

    def list_all_index(self) -> tuple[MemoryIndexRecord, ...]:
        return self._fetch_records(
            """SELECT * FROM memory_index
               ORDER BY memory_id, version"""
        )

    def get_version(self, memory_id: str, version: int) -> MemoryIndexRecord:
        row = self._fetchone(
            "SELECT * FROM memory_index WHERE memory_id = ? AND version = ?",
            (memory_id, version),
        )
        if row is None:
            raise MemoryRepositoryError(
                "Memory version was not found.",
                code=MemoryErrorCode.NOT_FOUND,
            )
        return _record_from_row(row)

    def insert_active(self, record: MemoryIndexRecord) -> None:
        _require_active(record)
        if record.version != 1 or record.supersedes_memory_id is not None:
            raise _version_conflict()
        try:
            with self._conn:
                self._insert(record)
        except sqlite3.IntegrityError as exc:
            raise _version_conflict() from exc
        except sqlite3.Error as exc:
            raise _index_failure() from exc

    def supersede_and_insert(
        self, expected_version: int, new_record: MemoryIndexRecord
    ) -> None:
        _require_active(new_record)
        if (
            new_record.version != expected_version + 1
            or new_record.supersedes_memory_id != new_record.memory_id
            or new_record.supersedes_version != expected_version
        ):
            raise _version_conflict()
        try:
            with self._conn:
                cursor = self._conn.execute(
                    """UPDATE memory_index
                       SET status = 'superseded', updated_at = ?
                       WHERE memory_id = ? AND version = ? AND status = 'active'""",
                    (new_record.updated_at, new_record.memory_id, expected_version),
                )
                if cursor.rowcount != 1:
                    raise _version_conflict()
                self._insert(new_record)
        except MemoryRepositoryError:
            raise
        except sqlite3.IntegrityError as exc:
            raise _version_conflict() from exc
        except sqlite3.Error as exc:
            raise _index_failure() from exc

    def archive(
        self, memory_id: str, expected_version: int, *, updated_at: str
    ) -> MemoryIndexRecord:
        try:
            with self._conn:
                row = self._conn.execute(
                    "SELECT * FROM memory_index WHERE memory_id = ? AND version = ?",
                    (memory_id, expected_version),
                ).fetchone()
                if row is None:
                    raise _version_conflict()
                current = _record_from_row(row)
                if current.status == MemoryStatus.ARCHIVED:
                    raise MemoryRepositoryError(
                        "Memory version is already archived.",
                        code=MemoryErrorCode.ALREADY_ARCHIVED,
                    )
                if current.status != MemoryStatus.ACTIVE:
                    raise _version_conflict()
                archived = replace(
                    current,
                    status=MemoryStatus.ARCHIVED,
                    updated_at=updated_at,
                )
                cursor = self._conn.execute(
                    """UPDATE memory_index SET status = 'archived', updated_at = ?
                       WHERE memory_id = ? AND version = ? AND status = 'active'""",
                    (updated_at, memory_id, expected_version),
                )
                if cursor.rowcount != 1:
                    raise _version_conflict()
        except MemoryRepositoryError:
            raise
        except (ValueError, sqlite3.Error) as exc:
            raise _index_failure() from exc
        return archived

    def list_versions(self, memory_id: str) -> tuple[MemoryIndexRecord, ...]:
        return self._fetch_records(
            """SELECT * FROM memory_index WHERE memory_id = ?
               ORDER BY version""",
            (memory_id,),
        )

    def list_archived(self) -> tuple[MemoryIndexRecord, ...]:
        return self._fetch_records(
            """SELECT * FROM memory_index WHERE status = 'archived'
               ORDER BY updated_at DESC, memory_id, version"""
        )

    def _insert(self, record: MemoryIndexRecord) -> None:
        self._conn.execute(
            """INSERT INTO memory_index (
                   memory_id, version, status, relative_path, content_hash,
                   tags_json, created_at, updated_at, supersedes_memory_id,
                   supersedes_version, source_session_id, source_turn_id,
                   source_run_id, source_tool_call_id, confirmation_ref, evidence_ref
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            _record_values(record),
        )

    def _fetchone(
        self, sql: str, parameters: tuple[object, ...]
    ) -> sqlite3.Row | None:
        try:
            return self._conn.execute(sql, parameters).fetchone()
        except sqlite3.Error as exc:
            raise _index_failure() from exc

    def _fetch_records(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> tuple[MemoryIndexRecord, ...]:
        try:
            rows = self._conn.execute(sql, parameters).fetchall()
            return tuple(_record_from_row(row) for row in rows)
        except (ValueError, sqlite3.Error) as exc:
            raise _index_failure() from exc


def _record_values(record: MemoryIndexRecord) -> tuple[object, ...]:
    return (
        record.memory_id,
        record.version,
        record.status.value,
        record.relative_path,
        record.content_hash,
        record.tags_json,
        record.created_at,
        record.updated_at,
        record.supersedes_memory_id,
        record.supersedes_version,
        record.source_session_id,
        record.source_turn_id,
        record.source_run_id,
        record.source_tool_call_id,
        record.confirmation_ref,
        record.evidence_ref,
    )


def _record_from_row(row: sqlite3.Row) -> MemoryIndexRecord:
    try:
        return MemoryIndexRecord(
            memory_id=str(row["memory_id"]),
            version=int(row["version"]),
            status=MemoryStatus(str(row["status"])),
            relative_path=str(row["relative_path"]),
            content_hash=str(row["content_hash"]),
            tags_json=str(row["tags_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            supersedes_memory_id=(
                str(row["supersedes_memory_id"])
                if row["supersedes_memory_id"] is not None
                else None
            ),
            supersedes_version=(
                int(row["supersedes_version"])
                if row["supersedes_version"] is not None
                else None
            ),
            source_session_id=str(row["source_session_id"]),
            source_turn_id=str(row["source_turn_id"]),
            source_run_id=str(row["source_run_id"]),
            source_tool_call_id=str(row["source_tool_call_id"]),
            confirmation_ref=str(row["confirmation_ref"]),
            evidence_ref=str(row["evidence_ref"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _index_failure() from exc


def _require_active(record: MemoryIndexRecord) -> None:
    if record.status != MemoryStatus.ACTIVE:
        raise MemoryRepositoryError(
            "Only an active Memory version can be inserted.",
            code=MemoryErrorCode.INVALID,
        )


def _version_conflict() -> MemoryRepositoryError:
    return MemoryRepositoryError(
        "Memory version does not match the committed active version.",
        code=MemoryErrorCode.VERSION_CONFLICT,
    )


def _index_failure() -> MemoryRepositoryError:
    return MemoryRepositoryError(
        "Memory index operation failed.",
        code=MemoryErrorCode.INDEX_FAILED,
    )
