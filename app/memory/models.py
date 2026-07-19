"""Immutable framework-independent models for Stage 9B Memory."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from app.common.validation import require_non_empty_string


_SAFE_MEMORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class MemoryDocument:
    memory_id: str
    version: int
    content: str
    relative_path: str
    content_hash: str

    def __post_init__(self) -> None:
        _validate_memory_id(self.memory_id)
        _positive_int(self.version, "version")
        require_non_empty_string(self.content, "content")
        _validate_relative_path(self.relative_path)
        if self.relative_path != memory_relative_path(self.memory_id, self.version):
            raise ValueError("relative_path must match memory identity and version.")
        _validate_hash(self.content_hash)
        if memory_content_hash(self.content) != self.content_hash:
            raise ValueError("content_hash must match content.")


@dataclass(frozen=True)
class MemoryIndexRecord:
    memory_id: str
    version: int
    status: MemoryStatus
    relative_path: str
    content_hash: str
    tags_json: str
    created_at: str
    updated_at: str
    supersedes_memory_id: str | None
    supersedes_version: int | None
    source_session_id: str
    source_turn_id: str
    source_run_id: str
    source_tool_call_id: str
    confirmation_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        _validate_memory_id(self.memory_id)
        _positive_int(self.version, "version")
        if not isinstance(self.status, MemoryStatus):
            raise ValueError("status must be a MemoryStatus.")
        _validate_relative_path(self.relative_path)
        if self.relative_path != memory_relative_path(self.memory_id, self.version):
            raise ValueError("relative_path must match memory identity and version.")
        _validate_hash(self.content_hash)
        decode_memory_tags(self.tags_json)
        for field_name in (
            "created_at",
            "updated_at",
            "source_session_id",
            "source_turn_id",
            "source_run_id",
            "source_tool_call_id",
            "confirmation_ref",
            "evidence_ref",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        if (self.supersedes_memory_id is None) != (
            self.supersedes_version is None
        ):
            raise ValueError("supersedes identity and version must appear together.")
        if self.version == 1:
            if self.supersedes_memory_id is not None:
                raise ValueError("version 1 cannot supersede another version.")
        else:
            if self.supersedes_memory_id != self.memory_id:
                raise ValueError("new versions must supersede the same memory_id.")
            if self.supersedes_version != self.version - 1:
                raise ValueError("new versions must supersede the previous version.")


@dataclass(frozen=True)
class MemoryWriteContext:
    """Committed provenance supplied only after the Tool confirmation boundary."""

    source_session_id: str
    source_turn_id: str
    source_run_id: str
    source_tool_call_id: str
    confirmation_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_session_id",
            "source_turn_id",
            "source_run_id",
            "source_tool_call_id",
            "confirmation_ref",
            "evidence_ref",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class MemoryEntry:
    document: MemoryDocument
    record: MemoryIndexRecord

    def __post_init__(self) -> None:
        if not isinstance(self.document, MemoryDocument):
            raise ValueError("document must be a MemoryDocument.")
        if not isinstance(self.record, MemoryIndexRecord):
            raise ValueError("record must be a MemoryIndexRecord.")
        if (
            self.document.memory_id != self.record.memory_id
            or self.document.version != self.record.version
            or self.document.relative_path != self.record.relative_path
            or self.document.content_hash != self.record.content_hash
        ):
            raise ValueError("document and index record must describe one version.")


@dataclass(frozen=True)
class MemorySaveResult:
    entry: MemoryEntry
    idempotent_existing: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.entry, MemoryEntry):
            raise ValueError("entry must be a MemoryEntry.")
        if not isinstance(self.idempotent_existing, bool):
            raise ValueError("idempotent_existing must be a bool.")


@dataclass(frozen=True)
class MemoryConflictCandidate:
    memory_id: str
    version: int
    content: str
    tags: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        _validate_memory_id(self.memory_id)
        _positive_int(self.version, "version")
        require_non_empty_string(self.content, "content")
        if not isinstance(self.tags, tuple):
            raise ValueError("tags must be a tuple.")
        for tag in self.tags:
            require_non_empty_string(tag, "tag")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must not contain duplicates.")
        require_non_empty_string(self.reason, "reason")


def memory_relative_path(memory_id: str, version: int) -> str:
    _validate_memory_id(memory_id)
    _positive_int(version, "version")
    return f"entries/{memory_id}/v{version}.md"


def memory_content_hash(content: str) -> str:
    require_non_empty_string(content, "content")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def encode_memory_tags(tags: tuple[str, ...]) -> str:
    if not isinstance(tags, tuple):
        raise ValueError("tags must be a tuple.")
    normalized: list[str] = []
    for tag in tags:
        require_non_empty_string(tag, "tag")
        value = tag.strip()
        if value in normalized:
            raise ValueError("tags must not contain duplicates.")
        normalized.append(value)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def decode_memory_tags(tags_json: str) -> tuple[str, ...]:
    require_non_empty_string(tags_json, "tags_json")
    try:
        payload = json.loads(tags_json)
    except json.JSONDecodeError as exc:
        raise ValueError("tags_json must contain a JSON array.") from exc
    if not isinstance(payload, list) or any(not isinstance(item, str) for item in payload):
        raise ValueError("tags_json must contain strings.")
    tags = tuple(item.strip() for item in payload)
    if any(not item for item in tags) or len(set(tags)) != len(tags):
        raise ValueError("tags_json values must be unique and non-empty.")
    if tags_json != encode_memory_tags(tags):
        raise ValueError("tags_json must use canonical encoding.")
    return tags


def _validate_memory_id(memory_id: str) -> None:
    require_non_empty_string(memory_id, "memory_id")
    if not _SAFE_MEMORY_ID.fullmatch(memory_id):
        raise ValueError("memory_id must be a safe system identifier.")


def _validate_relative_path(relative_path: str) -> None:
    require_non_empty_string(relative_path, "relative_path")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or "\\" in relative_path:
        raise ValueError("relative_path must stay below the Memory root.")


def _validate_hash(content_hash: str) -> None:
    require_non_empty_string(content_hash, "content_hash")
    if not _SHA256.fullmatch(content_hash):
        raise ValueError("content_hash must be a lowercase SHA-256 digest.")


def _positive_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")
