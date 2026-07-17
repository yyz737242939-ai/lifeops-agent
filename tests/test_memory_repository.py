from __future__ import annotations

import unittest

from app.memory.errors import MemoryErrorCode, MemoryRepositoryError
from app.memory.models import (
    MemoryIndexRecord,
    MemoryStatus,
    encode_memory_tags,
    memory_relative_path,
)
from app.memory.repository import SqliteMemoryRepository
from tests.helpers import create_test_connection


class SqliteMemoryRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repository = SqliteMemoryRepository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_insert_get_list_and_duplicate_lookup_store_metadata_only(self) -> None:
        record = _record(1)

        self.repository.insert_active(record)

        self.assertEqual(self.repository.get_version("memory_1", 1), record)
        self.assertEqual(self.repository.list_active_index(), (record,))
        self.assertEqual(self.repository.find_active_duplicate(record.content_hash), record)
        self.assertEqual(self.repository.list_versions("memory_1"), (record,))
        self.assertNotIn(
            "content",
            tuple(
                row["name"]
                for row in self.conn.execute("PRAGMA table_info(memory_index)").fetchall()
            ),
        )

    def test_supersede_and_insert_is_one_atomic_version_transition(self) -> None:
        first = _record(1)
        second = _record(
            2,
            content_hash="b" * 64,
            updated_at="2026-07-16T01:00:00Z",
            supersedes_memory_id="memory_1",
            supersedes_version=1,
        )
        self.repository.insert_active(first)

        self.repository.supersede_and_insert(1, second)

        versions = self.repository.list_versions("memory_1")
        self.assertEqual(
            tuple(record.status for record in versions),
            (MemoryStatus.SUPERSEDED, MemoryStatus.ACTIVE),
        )
        self.assertEqual(versions[0].updated_at, second.updated_at)
        self.assertEqual(self.repository.list_active_index(), (second,))

    def test_stale_update_rolls_back_without_changing_active_version(self) -> None:
        first = _record(1)
        self.repository.insert_active(first)
        invalid_next = _record(
            3,
            content_hash="c" * 64,
            supersedes_memory_id="memory_1",
            supersedes_version=2,
        )

        with self.assertRaises(MemoryRepositoryError) as caught:
            self.repository.supersede_and_insert(2, invalid_next)

        self.assertEqual(caught.exception.code, MemoryErrorCode.VERSION_CONFLICT.value)
        self.assertEqual(self.repository.list_versions("memory_1"), (first,))

    def test_insert_constraint_failure_rolls_back_supersede(self) -> None:
        first = _record(1)
        self.repository.insert_active(first)
        self.conn.execute(
            """INSERT INTO memory_index (
                   memory_id, version, status, relative_path, content_hash,
                   tags_json, created_at, updated_at, supersedes_memory_id,
                   supersedes_version, source_session_id, source_turn_id,
                   source_run_id, source_tool_call_id, confirmation_ref, evidence_ref
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "memory_2",
                1,
                "archived",
                memory_relative_path("memory_1", 2),
                "b" * 64,
                encode_memory_tags(("legacy",)),
                "2026-07-16T00:00:00Z",
                "2026-07-16T00:00:00Z",
                None,
                None,
                "session_1",
                "turn_1",
                "run_1",
                "call_1",
                "confirmation_1",
                "evidence_1",
            ),
        )
        self.conn.commit()
        second = _record(
            2,
            content_hash="c" * 64,
            supersedes_memory_id="memory_1",
            supersedes_version=1,
        )

        with self.assertRaises(MemoryRepositoryError) as caught:
            self.repository.supersede_and_insert(1, second)

        self.assertEqual(caught.exception.code, MemoryErrorCode.VERSION_CONFLICT.value)
        self.assertEqual(
            self.repository.get_version("memory_1", 1).status,
            MemoryStatus.ACTIVE,
        )

    def test_archive_changes_only_lifecycle_and_is_idempotency_safe(self) -> None:
        active = _record(1)
        self.repository.insert_active(active)

        archived = self.repository.archive(
            "memory_1", 1, updated_at="2026-07-16T02:00:00Z"
        )

        self.assertEqual(archived.status, MemoryStatus.ARCHIVED)
        self.assertEqual(self.repository.list_active_index(), ())
        self.assertEqual(self.repository.list_archived(), (archived,))
        with self.assertRaises(MemoryRepositoryError) as caught:
            self.repository.archive(
                "memory_1", 1, updated_at="2026-07-16T03:00:00Z"
            )
        self.assertEqual(caught.exception.code, MemoryErrorCode.ALREADY_ARCHIVED.value)

    def test_missing_version_and_duplicate_active_fail_with_stable_codes(self) -> None:
        with self.assertRaises(MemoryRepositoryError) as missing:
            self.repository.get_version("missing", 1)
        self.assertEqual(missing.exception.code, MemoryErrorCode.NOT_FOUND.value)

        active = _record(1)
        self.repository.insert_active(active)
        with self.assertRaises(MemoryRepositoryError) as duplicate:
            self.repository.insert_active(active)
        self.assertEqual(duplicate.exception.code, MemoryErrorCode.VERSION_CONFLICT.value)

        direct_v2 = _record(
            2,
            content_hash="b" * 64,
            supersedes_memory_id="memory_1",
            supersedes_version=1,
        )
        with self.assertRaises(MemoryRepositoryError) as skipped_version:
            self.repository.insert_active(direct_v2)
        self.assertEqual(
            skipped_version.exception.code,
            MemoryErrorCode.VERSION_CONFLICT.value,
        )

    def test_invalid_archive_timestamp_does_not_commit_lifecycle_change(self) -> None:
        active = _record(1)
        self.repository.insert_active(active)

        with self.assertRaises(MemoryRepositoryError) as caught:
            self.repository.archive("memory_1", 1, updated_at=" ")

        self.assertEqual(caught.exception.code, MemoryErrorCode.INDEX_FAILED.value)
        self.assertEqual(self.repository.get_version("memory_1", 1), active)


def _record(
    version: int,
    *,
    memory_id: str = "memory_1",
    content_hash: str = "a" * 64,
    updated_at: str = "2026-07-16T00:00:00Z",
    supersedes_memory_id: str | None = None,
    supersedes_version: int | None = None,
) -> MemoryIndexRecord:
    return MemoryIndexRecord(
        memory_id=memory_id,
        version=version,
        status=MemoryStatus.ACTIVE,
        relative_path=memory_relative_path(memory_id, version),
        content_hash=content_hash,
        tags_json=encode_memory_tags(("偏好",)),
        created_at="2026-07-16T00:00:00Z",
        updated_at=updated_at,
        supersedes_memory_id=supersedes_memory_id,
        supersedes_version=supersedes_version,
        source_session_id="session_1",
        source_turn_id="turn_1",
        source_run_id="run_1",
        source_tool_call_id="call_1",
        confirmation_ref="confirmation_1",
        evidence_ref="evidence_1",
    )


if __name__ == "__main__":
    unittest.main()
