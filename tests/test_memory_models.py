from __future__ import annotations

import unittest
from dataclasses import fields

from app.memory.errors import (
    MemoryContractError,
    MemoryDocumentStoreError,
    MemoryErrorCode,
    MemoryRepositoryError,
)
from app.memory.models import (
    MemoryDocument,
    MemoryIndexRecord,
    MemoryStatus,
    decode_memory_tags,
    encode_memory_tags,
    memory_content_hash,
    memory_relative_path,
)


class MemoryModelsTest(unittest.TestCase):
    def test_public_fields_statuses_and_error_codes_are_frozen(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(MemoryDocument)),
            ("memory_id", "version", "content", "relative_path", "content_hash"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(MemoryIndexRecord)),
            (
                "memory_id",
                "version",
                "status",
                "relative_path",
                "content_hash",
                "tags_json",
                "created_at",
                "updated_at",
                "supersedes_memory_id",
                "supersedes_version",
                "source_session_id",
                "source_turn_id",
                "source_run_id",
                "source_tool_call_id",
                "confirmation_ref",
                "evidence_ref",
            ),
        )
        self.assertEqual(
            tuple(item.value for item in MemoryStatus),
            ("active", "superseded", "archived"),
        )
        self.assertEqual(
            tuple(item.value for item in MemoryErrorCode),
            (
                "memory_invalid",
                "memory_path_invalid",
                "memory_file_write_failed",
                "memory_file_read_failed",
                "memory_file_missing",
                "memory_hash_mismatch",
                "memory_index_failed",
                "memory_not_found",
                "memory_version_conflict",
                "memory_already_archived",
            ),
        )

    def test_document_and_index_accept_exact_versioned_identity(self) -> None:
        content = "用户确认的长期信息。"
        document = MemoryDocument(
            "memory_1",
            1,
            content,
            memory_relative_path("memory_1", 1),
            memory_content_hash(content),
        )
        record = _record(1, content_hash=document.content_hash)

        self.assertEqual(document.relative_path, "entries/memory_1/v1.md")
        self.assertEqual(record.status, MemoryStatus.ACTIVE)
        self.assertEqual(decode_memory_tags(record.tags_json), ("偏好", "出行"))

    def test_update_version_requires_same_memory_and_immediate_predecessor(self) -> None:
        updated = _record(
            2,
            supersedes_memory_id="memory_1",
            supersedes_version=1,
        )
        self.assertEqual(updated.version, 2)

        invalid = (
            {"version": 1, "supersedes_memory_id": "memory_1", "supersedes_version": 1},
            {"version": 2, "supersedes_memory_id": None, "supersedes_version": None},
            {"version": 2, "supersedes_memory_id": "memory_other", "supersedes_version": 1},
            {"version": 3, "supersedes_memory_id": "memory_1", "supersedes_version": 1},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _record(**changes)

    def test_paths_hashes_tags_and_versions_fail_closed(self) -> None:
        content = "confirmed"
        invalid_documents = (
            ("../escape", 1, "entries/escape/v1.md", memory_content_hash(content)),
            ("memory_1", 0, "entries/memory_1/v0.md", memory_content_hash(content)),
            ("memory_1", 1, "../escape.md", memory_content_hash(content)),
            ("memory_1", 1, "entries/memory_1/v2.md", memory_content_hash(content)),
            ("memory_1", 1, "entries/memory_1/v1.md", "0" * 64),
        )
        for memory_id, version, path, content_hash in invalid_documents:
            with self.subTest(path=path), self.assertRaises(ValueError):
                MemoryDocument(memory_id, version, content, path, content_hash)

        invalid_tags = ("{}", '["ok", "ok"]', '[" "]', '["ok"] ', '[1]')
        for tags_json in invalid_tags:
            with self.subTest(tags_json=tags_json), self.assertRaises(ValueError):
                decode_memory_tags(tags_json)
        with self.assertRaises(ValueError):
            encode_memory_tags(("duplicate", "duplicate"))

    def test_expected_errors_keep_stable_codes_and_safe_messages(self) -> None:
        error_types = (
            MemoryContractError,
            MemoryRepositoryError,
            MemoryDocumentStoreError,
        )
        for error_type in error_types:
            with self.subTest(error_type=error_type):
                error = error_type(
                    "Safe Memory failure.",
                    code=MemoryErrorCode.INVALID,
                )
                self.assertEqual(error.code, MemoryErrorCode.INVALID.value)
                self.assertEqual(str(error), "Safe Memory failure.")


def _record(
    version: int,
    *,
    content_hash: str | None = None,
    supersedes_memory_id: str | None = None,
    supersedes_version: int | None = None,
) -> MemoryIndexRecord:
    return MemoryIndexRecord(
        memory_id="memory_1",
        version=version,
        status=MemoryStatus.ACTIVE,
        relative_path=memory_relative_path("memory_1", version),
        content_hash=content_hash or ("a" * 64),
        tags_json=encode_memory_tags(("偏好", "出行")),
        created_at="2026-07-16T00:00:00Z",
        updated_at="2026-07-16T00:00:00Z",
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
