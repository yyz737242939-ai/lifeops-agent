"""UTF-8 JSON Lines repository for session-local visible conversation."""

from __future__ import annotations

import json
import re
import threading
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.context.errors import (
    ContextErrorCode,
    ConversationRepositoryError,
)
from app.context.models import (
    ConversationRole,
    ConversationSummary,
    ConversationTurn,
    ConversationTurnKind,
)


CONVERSATION_SCHEMA_VERSION = 1
CONVERSATION_CONCURRENCY_POLICY = "process_local_serialized_append"
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOCKS_GUARD = threading.Lock()
_SESSION_LOCKS: dict[str, threading.RLock] = {}
_TURN_KEYS = {
    "schema_version",
    "session_id",
    "turn_id",
    "sequence",
    "role",
    "kind",
    "content",
    "run_id",
    "created_at",
}
_SUMMARY_KEYS = {
    "schema_version",
    "session_id",
    "summary_id",
    "version",
    "covered_start_sequence",
    "covered_end_sequence",
    "content",
    "estimated_tokens",
    "previous_summary_id",
    "source_turn_ids",
    "provider",
    "model",
    "created_at",
}


class CorruptTailPolicy(StrEnum):
    """V1 reports any damaged JSONL tail instead of silently skipping content."""

    FAIL = "fail"


class JsonlConversationRepository:
    """Store each validated session in independent turns and summaries files."""

    def __init__(
        self,
        root: Path,
        *,
        corrupt_tail_policy: CorruptTailPolicy = CorruptTailPolicy.FAIL,
    ) -> None:
        if not isinstance(root, Path):
            raise ValueError("root must be a Path.")
        if not isinstance(corrupt_tail_policy, CorruptTailPolicy):
            raise ValueError("corrupt_tail_policy must be a CorruptTailPolicy.")
        self._root = root
        self._corrupt_tail_policy = corrupt_tail_policy

    def append_turn(self, turn: ConversationTurn) -> None:
        if not isinstance(turn, ConversationTurn):
            raise ValueError("turn must be a ConversationTurn.")
        path = self._session_file(turn.session_id, "turns.jsonl")
        with self._session_lock(turn.session_id):
            existing = tuple(
                self._turn_from_payload(row)
                for row in self._read_json_lines(
                    path, ContextErrorCode.CORRUPT_TAIL
                )
            )
            self._validate_turn_sequence(existing, turn.session_id)
            expected_sequence = len(existing) + 1
            if turn.sequence != expected_sequence or any(
                item.turn_id == turn.turn_id for item in existing
            ):
                raise ConversationRepositoryError(
                    "Conversation turn sequence is not the next append position.",
                    code=ContextErrorCode.SEQUENCE_INVALID,
                )
            self._append_json_line(
                path,
                {
                    "schema_version": turn.schema_version,
                    "session_id": turn.session_id,
                    "turn_id": turn.turn_id,
                    "sequence": turn.sequence,
                    "role": turn.role.value,
                    "kind": turn.kind.value,
                    "content": turn.content,
                    "run_id": turn.run_id,
                    "created_at": turn.created_at,
                },
                ContextErrorCode.TURN_APPEND_FAILED,
            )

    def load_turns(
        self,
        session_id: str,
        before_or_at_sequence: int | None,
        limit: int | None,
    ) -> tuple[ConversationTurn, ...]:
        if before_or_at_sequence is not None and (
            not isinstance(before_or_at_sequence, int)
            or isinstance(before_or_at_sequence, bool)
            or before_or_at_sequence < 1
        ):
            raise ValueError("before_or_at_sequence must be positive when provided.")
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
        ):
            raise ValueError("limit must be positive when provided.")
        path = self._session_file(session_id, "turns.jsonl")
        with self._session_lock(session_id):
            rows = self._read_json_lines(path, ContextErrorCode.CORRUPT_TAIL)
            turns = tuple(self._turn_from_payload(row) for row in rows)
        self._validate_turn_sequence(turns, session_id)
        selected = tuple(
            turn
            for turn in turns
            if before_or_at_sequence is None
            or turn.sequence <= before_or_at_sequence
        )
        return selected if limit is None else selected[-limit:]

    def append_summary(self, summary: ConversationSummary) -> None:
        if not isinstance(summary, ConversationSummary):
            raise ValueError("summary must be a ConversationSummary.")
        path = self._session_file(summary.session_id, "summaries.jsonl")
        with self._session_lock(summary.session_id):
            existing = tuple(
                self._summary_from_payload(row)
                for row in self._read_json_lines(
                    path, ContextErrorCode.SUMMARY_INVALID
                )
            )
            self._validate_summary_sequence(existing, summary.session_id)
            previous = existing[-1] if existing else None
            if (
                summary.version != len(existing) + 1
                or (
                    previous is None
                    and summary.previous_summary_id is not None
                )
                or (
                    previous is not None
                    and summary.previous_summary_id != previous.summary_id
                )
                or (
                    previous is not None
                    and summary.covered_end_sequence
                    <= previous.covered_end_sequence
                )
                or any(item.summary_id == summary.summary_id for item in existing)
            ):
                raise ConversationRepositoryError(
                    "Conversation summary version chain is invalid.",
                    code=ContextErrorCode.SEQUENCE_INVALID,
                )
            self._append_json_line(
                path,
                {
                    "schema_version": summary.schema_version,
                    "session_id": summary.session_id,
                    "summary_id": summary.summary_id,
                    "version": summary.version,
                    "covered_start_sequence": summary.covered_start_sequence,
                    "covered_end_sequence": summary.covered_end_sequence,
                    "content": summary.content,
                    "estimated_tokens": summary.estimated_tokens,
                    "previous_summary_id": summary.previous_summary_id,
                    "source_turn_ids": list(summary.source_turn_ids),
                    "provider": summary.provider,
                    "model": summary.model,
                    "created_at": summary.created_at,
                },
                ContextErrorCode.CONVERSATION_PERSIST_FAILED,
            )

    def load_latest_valid_summary(
        self, session_id: str
    ) -> ConversationSummary | None:
        path = self._session_file(session_id, "summaries.jsonl")
        with self._session_lock(session_id):
            rows = self._read_json_lines(path, ContextErrorCode.SUMMARY_INVALID)
            summaries = tuple(self._summary_from_payload(row) for row in rows)
        self._validate_summary_sequence(summaries, session_id)
        return summaries[-1] if summaries else None

    def _session_lock(self, session_id: str) -> threading.RLock:
        session_path = str(self._root.resolve() / session_id).casefold()
        with _LOCKS_GUARD:
            return _SESSION_LOCKS.setdefault(session_path, threading.RLock())

    def _session_file(self, session_id: str, filename: str) -> Path:
        if not isinstance(session_id, str) or not _SAFE_SESSION_ID.fullmatch(session_id):
            raise ConversationRepositoryError(
                "The session identifier is not safe for conversation storage.",
                code=ContextErrorCode.PATH_INVALID,
            )
        session_root = self._root / session_id
        resolved_root = self._root.resolve()
        resolved_session = session_root.resolve()
        if resolved_session.parent != resolved_root:
            raise ConversationRepositoryError(
                "The session path is outside the conversation root.",
                code=ContextErrorCode.PATH_INVALID,
            )
        return session_root / filename

    @staticmethod
    def _append_json_line(
        path: Path, payload: dict[str, Any], error_code: ContextErrorCode
    ) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush()
        except (OSError, TypeError, ValueError) as exc:
            raise ConversationRepositoryError(
                "Conversation data could not be appended safely.",
                code=error_code,
            ) from exc

    @staticmethod
    def _read_json_lines(
        path: Path, invalid_code: ContextErrorCode
    ) -> tuple[dict[str, Any], ...]:
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ConversationRepositoryError(
                "Conversation data could not be read safely.",
                code=ContextErrorCode.HISTORY_READ_FAILED,
            ) from exc
        rows: list[dict[str, Any]] = []
        for line in lines:
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ConversationRepositoryError(
                    "Conversation data contains an invalid JSON line.",
                    code=invalid_code,
                ) from exc
            if not isinstance(payload, dict):
                raise ConversationRepositoryError(
                    "Conversation data contains a non-object JSON line.",
                    code=invalid_code,
                )
            rows.append(payload)
        return tuple(rows)

    @staticmethod
    def _validate_turn_sequence(
        turns: tuple[ConversationTurn, ...], session_id: str
    ) -> None:
        expected = tuple(range(1, len(turns) + 1))
        if (
            tuple(turn.sequence for turn in turns) != expected
            or any(turn.session_id != session_id for turn in turns)
            or len({turn.turn_id for turn in turns}) != len(turns)
        ):
            raise ConversationRepositoryError(
                "Conversation turn sequence is invalid.",
                code=ContextErrorCode.SEQUENCE_INVALID,
            )

    @staticmethod
    def _validate_summary_sequence(
        summaries: tuple[ConversationSummary, ...], session_id: str
    ) -> None:
        for index, summary in enumerate(summaries):
            previous = summaries[index - 1] if index else None
            if (
                summary.session_id != session_id
                or summary.version != index + 1
                or (
                    previous is None
                    and summary.previous_summary_id is not None
                )
                or (
                    previous is not None
                    and summary.previous_summary_id != previous.summary_id
                )
                or (
                    previous is not None
                    and summary.covered_end_sequence
                    <= previous.covered_end_sequence
                )
            ):
                raise ConversationRepositoryError(
                    "Conversation summary version chain is invalid.",
                    code=ContextErrorCode.SEQUENCE_INVALID,
                )
        if len({summary.summary_id for summary in summaries}) != len(summaries):
            raise ConversationRepositoryError(
                "Conversation summary identifiers are not unique.",
                code=ContextErrorCode.SEQUENCE_INVALID,
            )

    @staticmethod
    def _turn_from_payload(payload: dict[str, Any]) -> ConversationTurn:
        try:
            if set(payload) != _TURN_KEYS:
                raise ValueError("turn keys do not match the contract")
            if payload["schema_version"] != CONVERSATION_SCHEMA_VERSION:
                raise ValueError("unsupported turn schema version")
            return ConversationTurn(
                schema_version=payload["schema_version"],
                session_id=payload["session_id"],
                turn_id=payload["turn_id"],
                sequence=payload["sequence"],
                role=ConversationRole(payload["role"]),
                kind=ConversationTurnKind(payload["kind"]),
                content=payload["content"],
                run_id=payload["run_id"],
                created_at=payload["created_at"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversationRepositoryError(
                "Conversation turn does not match the frozen contract.",
                code=ContextErrorCode.CORRUPT_TAIL,
            ) from exc

    @staticmethod
    def _summary_from_payload(payload: dict[str, Any]) -> ConversationSummary:
        try:
            if set(payload) != _SUMMARY_KEYS:
                raise ValueError("summary keys do not match the contract")
            if payload["schema_version"] != CONVERSATION_SCHEMA_VERSION:
                raise ValueError("unsupported summary schema version")
            source_turn_ids = payload["source_turn_ids"]
            if not isinstance(source_turn_ids, list):
                raise ValueError("source_turn_ids must be a list")
            return ConversationSummary(
                schema_version=payload["schema_version"],
                session_id=payload["session_id"],
                summary_id=payload["summary_id"],
                version=payload["version"],
                covered_start_sequence=payload["covered_start_sequence"],
                covered_end_sequence=payload["covered_end_sequence"],
                content=payload["content"],
                estimated_tokens=payload["estimated_tokens"],
                previous_summary_id=payload["previous_summary_id"],
                source_turn_ids=tuple(source_turn_ids),
                provider=payload["provider"],
                model=payload["model"],
                created_at=payload["created_at"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversationRepositoryError(
                "Conversation summary does not match the frozen contract.",
                code=ContextErrorCode.SUMMARY_INVALID,
            ) from exc
