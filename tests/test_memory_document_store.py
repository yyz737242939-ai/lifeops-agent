from __future__ import annotations

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.memory.document_store import MemoryDocumentStore
from app.memory.errors import MemoryDocumentStoreError, MemoryErrorCode
from app.memory.models import memory_content_hash


class MemoryDocumentStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.store = MemoryDocumentStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_write_uses_exact_version_path_and_verified_read(self) -> None:
        content = "# 已确认记忆\n\n用户偏好靠窗座位。\n"

        written = self.store.write_immutable("memory_1", 1, content)
        loaded = self.store.read_verified(written.relative_path, written.content_hash)

        self.assertEqual(written, loaded)
        self.assertEqual(written.relative_path, "entries/memory_1/v1.md")
        self.assertEqual(written.content_hash, memory_content_hash(content))
        self.assertEqual(
            (self.root / written.relative_path).read_bytes(),
            content.encode("utf-8"),
        )

    def test_existing_version_is_never_overwritten(self) -> None:
        original = self.store.write_immutable("memory_1", 1, "original")

        with self.assertRaises(MemoryDocumentStoreError) as caught:
            self.store.write_immutable("memory_1", 1, "replacement")

        self.assertEqual(caught.exception.code, MemoryErrorCode.VERSION_CONFLICT.value)
        self.assertEqual(
            self.store.read_verified(original.relative_path, original.content_hash).content,
            "original",
        )

    def test_concurrent_store_instances_cannot_overwrite_one_version(self) -> None:
        stores = (MemoryDocumentStore(self.root), MemoryDocumentStore(self.root))

        def write(index: int) -> str:
            try:
                stores[index].write_immutable("memory_1", 1, f"content-{index}")
                return "written"
            except MemoryDocumentStoreError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(write, (0, 1)))

        self.assertEqual(outcomes.count("written"), 1)
        self.assertEqual(
            outcomes.count(MemoryErrorCode.VERSION_CONFLICT.value),
            1,
        )
        self.assertIn(
            (self.root / "entries" / "memory_1" / "v1.md").read_text(
                encoding="utf-8"
            ),
            {"content-0", "content-1"},
        )

    def test_invalid_identity_paths_and_hashes_fail_closed(self) -> None:
        invalid_writes = (("../escape", 1), ("memory_1", 0), ("memory/1", 1))
        for memory_id, version in invalid_writes:
            with self.subTest(memory_id=memory_id), self.assertRaises(
                MemoryDocumentStoreError
            ) as caught:
                self.store.write_immutable(memory_id, version, "content")
            self.assertEqual(caught.exception.code, MemoryErrorCode.PATH_INVALID.value)

        invalid_reads = (
            "../escape.md",
            "/absolute/v1.md",
            "entries\\memory_1\\v1.md",
            "entries/memory_1/v01.md",
            "entries/memory_1/v1.txt",
        )
        for path in invalid_reads:
            with self.subTest(path=path), self.assertRaises(
                MemoryDocumentStoreError
            ) as caught:
                self.store.read_verified(path, "a" * 64)
            self.assertEqual(caught.exception.code, MemoryErrorCode.PATH_INVALID.value)

        with self.assertRaises(MemoryDocumentStoreError) as invalid_hash:
            self.store.read_verified("entries/memory_1/v1.md", "not-a-hash")
        self.assertEqual(invalid_hash.exception.code, MemoryErrorCode.PATH_INVALID.value)

    def test_missing_tampered_and_invalid_utf8_have_distinct_safe_failures(self) -> None:
        with self.assertRaises(MemoryDocumentStoreError) as missing:
            self.store.read_verified("entries/memory_1/v1.md", "a" * 64)
        self.assertEqual(missing.exception.code, MemoryErrorCode.FILE_MISSING.value)

        written = self.store.write_immutable("memory_1", 1, "confirmed")
        (self.root / written.relative_path).write_text("tampered", encoding="utf-8")
        with self.assertRaises(MemoryDocumentStoreError) as mismatch:
            self.store.read_verified(written.relative_path, written.content_hash)
        self.assertEqual(mismatch.exception.code, MemoryErrorCode.HASH_MISMATCH.value)

        invalid_path = self.root / "entries" / "memory_2" / "v1.md"
        invalid_path.parent.mkdir(parents=True)
        invalid_path.write_bytes(b"\xff\xfe")
        with self.assertRaises(MemoryDocumentStoreError) as invalid_utf8:
            self.store.read_verified("entries/memory_2/v1.md", "b" * 64)
        self.assertEqual(invalid_utf8.exception.code, MemoryErrorCode.FILE_READ_FAILED.value)

    def test_failed_atomic_replace_cleans_temporary_file(self) -> None:
        with patch("app.memory.document_store.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(MemoryDocumentStoreError) as caught:
                self.store.write_immutable("memory_1", 1, "confirmed")

        self.assertEqual(caught.exception.code, MemoryErrorCode.FILE_WRITE_FAILED.value)
        target_dir = self.root / "entries" / "memory_1"
        self.assertEqual(tuple(target_dir.iterdir()), ())

    def test_symlink_escape_is_rejected_when_platform_allows_symlinks(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        entries = self.root / "entries"
        entries.mkdir(parents=True)
        try:
            os.symlink(outside, entries / "memory_1", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation is unavailable: {type(exc).__name__}")

        with self.assertRaises(MemoryDocumentStoreError) as caught:
            self.store.write_immutable("memory_1", 1, "confirmed")

        self.assertEqual(caught.exception.code, MemoryErrorCode.PATH_INVALID.value)
        self.assertFalse((outside / "v1.md").exists())

    def test_orphan_audit_reports_only_valid_uncommitted_documents(self) -> None:
        committed = self.store.write_immutable("memory_1", 1, "committed")
        orphan = self.store.write_immutable("memory_2", 1, "orphan")
        rogue = self.root / "entries" / "memory_3" / "notes.md"
        rogue.parent.mkdir(parents=True)
        rogue.write_text("not a version document", encoding="utf-8")

        self.assertEqual(
            self.store.audit_orphans((committed.relative_path,)),
            (orphan.relative_path,),
        )


if __name__ == "__main__":
    unittest.main()
