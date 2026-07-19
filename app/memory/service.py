"""Application service for confirmed long-term Memory lifecycle changes."""

from __future__ import annotations

from collections.abc import Callable

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.memory.document_store import MemoryDocumentStore
from app.memory.errors import MemoryError, MemoryErrorCode, MemoryRepositoryError
from app.memory.matching import memory_terms, normalize_memory_text
from app.memory.models import (
    MemoryConflictCandidate,
    MemoryEntry,
    MemoryIndexRecord,
    MemorySaveResult,
    MemoryStatus,
    MemoryWriteContext,
    decode_memory_tags,
    encode_memory_tags,
    memory_content_hash,
)
from app.memory.repository import MemoryRepository
from app.memory.retrieval_core import select_verified_active_entries


class MemoryService:
    def __init__(
        self,
        repository: MemoryRepository,
        document_store: MemoryDocumentStore,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._document_store = document_store
        self._id_factory = id_factory or (lambda: new_id("memory"))
        self._clock = clock or utc_now_iso

    def save_confirmed(
        self,
        content: str,
        tags: tuple[str, ...],
        write_context: MemoryWriteContext,
    ) -> MemorySaveResult:
        if not isinstance(write_context, MemoryWriteContext):
            raise ValueError("write_context must be a MemoryWriteContext.")
        normalized_content = _normalize_confirmed_content(content)
        tags_json = encode_memory_tags(tags)
        duplicate = self._repository.find_active_duplicate(
            memory_content_hash(normalized_content)
        )
        if duplicate is not None:
            document = self._document_store.read_verified(
                duplicate.relative_path,
                duplicate.content_hash,
            )
            return MemorySaveResult(
                MemoryEntry(document, duplicate),
                idempotent_existing=True,
            )

        conflicts = self.detect_conflicts(normalized_content, tags)
        if conflicts:
            raise MemoryConflictError(conflicts)

        memory_id = self._id_factory()
        now = self._clock()

        # File-first is intentional. A later index failure leaves an auditable,
        # non-retrievable orphan instead of an index row pointing at no content.
        document = self._document_store.write_immutable(
            memory_id,
            1,
            normalized_content,
        )
        record = MemoryIndexRecord(
            memory_id=memory_id,
            version=1,
            status=MemoryStatus.ACTIVE,
            relative_path=document.relative_path,
            content_hash=document.content_hash,
            tags_json=tags_json,
            created_at=now,
            updated_at=now,
            supersedes_memory_id=None,
            supersedes_version=None,
            source_session_id=write_context.source_session_id,
            source_turn_id=write_context.source_turn_id,
            source_run_id=write_context.source_run_id,
            source_tool_call_id=write_context.source_tool_call_id,
            confirmation_ref=write_context.confirmation_ref,
            evidence_ref=write_context.evidence_ref,
        )
        self._repository.insert_active(record)
        return MemorySaveResult(MemoryEntry(document, record))

    def audit_orphans(self) -> tuple[str, ...]:
        committed_paths = tuple(
            record.relative_path for record in self._repository.list_all_index()
        )
        return self._document_store.audit_orphans(committed_paths)

    def update_confirmed(
        self,
        memory_id: str,
        expected_version: int,
        new_content: str,
        tags: tuple[str, ...],
        write_context: MemoryWriteContext,
    ) -> MemorySaveResult:
        current = self._require_active_version(memory_id, expected_version)
        normalized_content = _normalize_confirmed_content(new_content)
        tags_json = encode_memory_tags(tags)
        new_hash = memory_content_hash(normalized_content)
        if new_hash == current.content_hash and tags_json == current.tags_json:
            document = self._document_store.read_verified(
                current.relative_path,
                current.content_hash,
            )
            return MemorySaveResult(
                MemoryEntry(document, current),
                idempotent_existing=True,
            )

        conflicts = self.detect_conflicts(
            normalized_content,
            tags,
            exclude_memory_id=memory_id,
        )
        if conflicts:
            raise MemoryConflictError(conflicts)

        new_version = expected_version + 1
        now = self._clock()
        document = self._document_store.write_immutable(
            memory_id,
            new_version,
            normalized_content,
        )
        record = MemoryIndexRecord(
            memory_id=memory_id,
            version=new_version,
            status=MemoryStatus.ACTIVE,
            relative_path=document.relative_path,
            content_hash=document.content_hash,
            tags_json=tags_json,
            created_at=now,
            updated_at=now,
            supersedes_memory_id=memory_id,
            supersedes_version=expected_version,
            source_session_id=write_context.source_session_id,
            source_turn_id=write_context.source_turn_id,
            source_run_id=write_context.source_run_id,
            source_tool_call_id=write_context.source_tool_call_id,
            confirmation_ref=write_context.confirmation_ref,
            evidence_ref=write_context.evidence_ref,
        )
        self._repository.supersede_and_insert(expected_version, record)
        return MemorySaveResult(MemoryEntry(document, record))

    def archive_confirmed(
        self,
        memory_id: str,
        expected_version: int,
        write_context: MemoryWriteContext,
    ) -> MemoryIndexRecord:
        # Requiring typed confirmed provenance keeps this application seam from
        # becoming an unstructured archive shortcut. Tool evidence remains the
        # action record; immutable version provenance is not overwritten.
        if not isinstance(write_context, MemoryWriteContext):
            raise ValueError("write_context must be a MemoryWriteContext.")
        self._require_archive_target(memory_id, expected_version)
        return self._repository.archive(
            memory_id,
            expected_version,
            updated_at=self._clock(),
        )

    def list_active(self) -> tuple[MemoryEntry, ...]:
        return self._load_entries(self._repository.list_active_index())

    def search(self, query: str, limit: int) -> tuple[MemoryEntry, ...]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
            raise ValueError("limit must be an integer between 1 and 10.")
        return tuple(
            item.entry
            for item in select_verified_active_entries(
                self._repository,
                self._document_store,
                query,
                max_items=limit,
                max_tokens=None,
            )
        )

    def list_archived(self) -> tuple[MemoryEntry, ...]:
        return self._load_entries(self._repository.list_archived())

    def list_history(self, memory_id: str) -> tuple[MemoryEntry, ...]:
        return self._load_entries(self._repository.list_versions(memory_id))

    def detect_conflicts(
        self,
        content: str,
        tags: tuple[str, ...],
        *,
        exclude_memory_id: str | None = None,
    ) -> tuple[MemoryConflictCandidate, ...]:
        normalized_content = _normalize_confirmed_content(content)
        normalized_tags = tuple(normalize_memory_text(tag) for tag in tags)
        content_terms = set(memory_terms(normalized_content))
        candidates: list[tuple[str, MemoryConflictCandidate]] = []
        for record in self._repository.list_active_index():
            if record.memory_id == exclude_memory_id:
                continue
            try:
                document = self._document_store.read_verified(
                    record.relative_path,
                    record.content_hash,
                )
            except MemoryError:
                continue
            existing_tags = decode_memory_tags(record.tags_json)
            normalized_existing_tags = {
                normalize_memory_text(tag) for tag in existing_tags
            }
            shared_tags = tuple(
                tag for tag in normalized_tags if tag in normalized_existing_tags
            )
            existing_normalized = normalize_memory_text(document.content)
            shared_terms = content_terms.intersection(memory_terms(document.content))
            substring_related = (
                normalize_memory_text(normalized_content) in existing_normalized
                or existing_normalized in normalize_memory_text(normalized_content)
            )
            reason: str | None = None
            if shared_tags:
                reason = "shared_tag"
            elif substring_related or len(shared_terms) >= 2:
                reason = "keyword_overlap"
            if reason is not None:
                candidates.append(
                    (
                        record.updated_at,
                        MemoryConflictCandidate(
                            memory_id=record.memory_id,
                            version=record.version,
                            content=document.content,
                            tags=existing_tags,
                            reason=reason,
                        ),
                    )
                )
        candidates.sort(key=lambda item: item[1].memory_id)
        candidates.sort(key=lambda item: item[0], reverse=True)
        return tuple(item[1] for item in candidates)

    def _require_active_version(
        self,
        memory_id: str,
        expected_version: int,
    ) -> MemoryIndexRecord:
        try:
            record = self._repository.get_version(memory_id, expected_version)
        except MemoryRepositoryError as exc:
            if exc.code == MemoryErrorCode.NOT_FOUND.value:
                raise _version_conflict() from exc
            raise
        if record.status != MemoryStatus.ACTIVE:
            raise _version_conflict()
        return record

    def _require_archive_target(
        self,
        memory_id: str,
        expected_version: int,
    ) -> MemoryIndexRecord:
        try:
            record = self._repository.get_version(memory_id, expected_version)
        except MemoryRepositoryError as exc:
            if exc.code == MemoryErrorCode.NOT_FOUND.value:
                raise _version_conflict() from exc
            raise
        if record.status == MemoryStatus.ARCHIVED:
            raise MemoryRepositoryError(
                "Memory version is already archived.",
                code=MemoryErrorCode.ALREADY_ARCHIVED,
            )
        if record.status != MemoryStatus.ACTIVE:
            raise _version_conflict()
        return record

    def _load_entries(
        self,
        records: tuple[MemoryIndexRecord, ...],
    ) -> tuple[MemoryEntry, ...]:
        entries: list[MemoryEntry] = []
        for record in records:
            try:
                document = self._document_store.read_verified(
                    record.relative_path,
                    record.content_hash,
                )
            except MemoryError:
                continue
            entries.append(MemoryEntry(document, record))
        return tuple(entries)


def _normalize_confirmed_content(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string.")
    return content.replace("\r\n", "\n").replace("\r", "\n").strip()


class MemoryConflictError(MemoryError):
    def __init__(self, candidates: tuple[MemoryConflictCandidate, ...]) -> None:
        if not candidates:
            raise ValueError("candidates must not be empty.")
        self.candidates = candidates
        super().__init__(
            "New Memory conflicts with an active candidate; update the target version instead.",
            code=MemoryErrorCode.VERSION_CONFLICT,
            details={
                "candidate_refs": tuple(
                    f"{candidate.memory_id}:v{candidate.version}"
                    for candidate in candidates
                )
            },
        )


def _version_conflict() -> MemoryRepositoryError:
    return MemoryRepositoryError(
        "Memory version does not match the committed active version.",
        code=MemoryErrorCode.VERSION_CONFLICT,
    )
