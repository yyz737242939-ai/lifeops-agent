"""Immutable UTF-8 Markdown storage for confirmed Memory content."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path

from app.memory.errors import MemoryDocumentStoreError, MemoryErrorCode
from app.memory.models import (
    MemoryDocument,
    memory_content_hash,
    memory_relative_path,
)


_MEMORY_PATH = re.compile(
    r"^entries/(?P<memory_id>[A-Za-z0-9][A-Za-z0-9_-]{0,127})/v(?P<version>[1-9][0-9]*)\.md$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[str, threading.RLock] = {}


class MemoryDocumentStore:
    """Store each system-generated Memory version once and verify every read."""

    def __init__(self, memory_root: Path) -> None:
        if not isinstance(memory_root, Path):
            raise ValueError("memory_root must be a Path.")
        self._root = memory_root

    def write_immutable(
        self, memory_id: str, version: int, content: str
    ) -> MemoryDocument:
        try:
            relative_path = memory_relative_path(memory_id, version)
            content_hash = memory_content_hash(content)
        except ValueError as exc:
            raise _path_failure() from exc

        with _root_lock(self._root):
            temporary_path: Path | None = None
            try:
                root = self._root.resolve()
                parent = root / "entries" / memory_id
                parent.mkdir(parents=True, exist_ok=True)
                resolved_parent = parent.resolve(strict=True)
                _require_direct_memory_parent(root, resolved_parent, memory_id)
                final_path = resolved_parent / f"v{version}.md"
                if final_path.exists():
                    raise MemoryDocumentStoreError(
                        "Memory version already exists and is immutable.",
                        code=MemoryErrorCode.VERSION_CONFLICT,
                    )

                payload = content.encode("utf-8")
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=resolved_parent,
                    prefix=".memory-",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(payload)
                    temporary.flush()
                    os.fsync(temporary.fileno())

                if final_path.exists():
                    raise MemoryDocumentStoreError(
                        "Memory version already exists and is immutable.",
                        code=MemoryErrorCode.VERSION_CONFLICT,
                    )
                os.replace(temporary_path, final_path)
                temporary_path = None
            except MemoryDocumentStoreError:
                raise
            except (OSError, UnicodeError) as exc:
                raise MemoryDocumentStoreError(
                    "Memory document could not be written.",
                    code=MemoryErrorCode.FILE_WRITE_FAILED,
                ) from exc
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass

        return MemoryDocument(
            memory_id=memory_id,
            version=version,
            content=content,
            relative_path=relative_path,
            content_hash=content_hash,
        )

    def read_verified(
        self, relative_path: str, expected_hash: str
    ) -> MemoryDocument:
        memory_id, version = _parse_relative_path(relative_path)
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            raise _path_failure()
        candidate = self._root / Path(*relative_path.split("/"))
        if not candidate.exists():
            raise MemoryDocumentStoreError(
                "Memory document is missing.",
                code=MemoryErrorCode.FILE_MISSING,
            )
        try:
            root = self._root.resolve()
            resolved = candidate.resolve(strict=True)
            expected = root / "entries" / memory_id / f"v{version}.md"
            if (
                candidate.is_symlink()
                or resolved != expected
                or not resolved.is_file()
            ):
                raise _path_failure()
            content = resolved.read_text(encoding="utf-8")
            actual_hash = memory_content_hash(content)
        except MemoryDocumentStoreError:
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise MemoryDocumentStoreError(
                "Memory document could not be read safely.",
                code=MemoryErrorCode.FILE_READ_FAILED,
            ) from exc
        if actual_hash != expected_hash:
            raise MemoryDocumentStoreError(
                "Memory document content hash does not match its index.",
                code=MemoryErrorCode.HASH_MISMATCH,
            )
        return MemoryDocument(
            memory_id=memory_id,
            version=version,
            content=content,
            relative_path=relative_path,
            content_hash=actual_hash,
        )

    def audit_orphans(
        self, committed_relative_paths: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not isinstance(committed_relative_paths, tuple):
            raise _path_failure()
        committed: set[str] = set()
        for relative_path in committed_relative_paths:
            _parse_relative_path(relative_path)
            committed.add(relative_path)
        try:
            root = self._root.resolve()
            entries = root / "entries"
            if not entries.exists():
                return ()
            discovered: list[str] = []
            for candidate in entries.glob("*/v*.md"):
                relative_path = candidate.relative_to(root).as_posix()
                try:
                    memory_id, version = _parse_relative_path(relative_path)
                    expected = root / "entries" / memory_id / f"v{version}.md"
                    if (
                        candidate.is_symlink()
                        or candidate.resolve(strict=True) != expected
                        or not candidate.is_file()
                    ):
                        continue
                except (MemoryDocumentStoreError, OSError, ValueError):
                    continue
                if relative_path not in committed:
                    discovered.append(relative_path)
            return tuple(sorted(discovered))
        except OSError as exc:
            raise MemoryDocumentStoreError(
                "Memory orphan audit failed.",
                code=MemoryErrorCode.FILE_READ_FAILED,
            ) from exc


def _parse_relative_path(relative_path: str) -> tuple[str, int]:
    if not isinstance(relative_path, str):
        raise _path_failure()
    match = _MEMORY_PATH.fullmatch(relative_path)
    if match is None:
        raise _path_failure()
    memory_id = match.group("memory_id")
    version = int(match.group("version"))
    if relative_path != memory_relative_path(memory_id, version):
        raise _path_failure()
    return memory_id, version


def _require_direct_memory_parent(root: Path, parent: Path, memory_id: str) -> None:
    if parent != root / "entries" / memory_id or not parent.is_dir():
        raise _path_failure()


def _root_lock(root: Path) -> threading.RLock:
    key = str(root.resolve()).casefold()
    with _LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(key, threading.RLock())


def _path_failure() -> MemoryDocumentStoreError:
    return MemoryDocumentStoreError(
        "Memory document path is invalid.",
        code=MemoryErrorCode.PATH_INVALID,
    )
