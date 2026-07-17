from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.context.errors import ContextErrorCode, ConversationRepositoryError
from app.context.models import (
    ConversationRole,
    ConversationSummary,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.repository import (
    CONVERSATION_SCHEMA_VERSION,
    JsonlConversationRepository,
)


class ContextRepositoryTest(unittest.TestCase):
    def test_turns_append_and_load_in_stable_utf8_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            repository = JsonlConversationRepository(root)
            turns = (
                _turn(1, "turn_1", "今天讨论 Context。", ConversationRole.USER),
                _turn(2, "turn_2", "好的。", ConversationRole.ASSISTANT),
                _turn(3, "turn_3", "继续。", ConversationRole.USER),
            )
            for turn in turns:
                repository.append_turn(turn)

            self.assertEqual(repository.load_turns("session_1", 3, 2), turns[1:])
            self.assertEqual(repository.load_turns("session_1", 2, 10), turns[:2])
            raw = (root / "session_1" / "turns.jsonl").read_text(encoding="utf-8")
            self.assertIn("今天讨论 Context。", raw)
            self.assertTrue(raw.endswith("\n"))
            self.assertEqual(len(raw.splitlines()), 3)

    def test_summary_append_and_latest_load_preserve_utf8_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            repository = JsonlConversationRepository(root)
            first = _summary(1, "summary_1", None, 1)
            second = _summary(2, "summary_2", "summary_1", 2)

            repository.append_summary(first)
            repository.append_summary(second)

            self.assertEqual(repository.load_latest_valid_summary("session_1"), second)
            rows = [
                json.loads(line)
                for line in (root / "session_1" / "summaries.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(rows[1]["content"], "已确认的中文摘要。")
            self.assertEqual(rows[1]["source_turn_ids"], ["turn_1", "turn_2"])

    def test_missing_session_is_empty_and_does_not_create_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            repository = JsonlConversationRepository(root)

            self.assertEqual(repository.load_turns("missing", 10, 5), ())
            self.assertIsNone(repository.load_latest_valid_summary("missing"))
            self.assertFalse(root.exists())

    def test_session_path_is_validated_before_io(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            repository = JsonlConversationRepository(root)

            for session_id in ("../escape", "nested/session", "", ".", "中文"):
                with self.subTest(session_id=session_id), self.assertRaises(
                    ConversationRepositoryError
                ) as caught:
                    repository.load_turns(session_id, 1, 1)
                self.assertEqual(caught.exception.code, ContextErrorCode.PATH_INVALID.value)
            self.assertFalse((Path(directory) / "escape").exists())

    def test_non_contract_json_object_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conversations" / "session_1" / "turns.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text('{"unexpected":true}\n', encoding="utf-8")
            repository = JsonlConversationRepository(Path(directory) / "conversations")

            with self.assertRaises(ConversationRepositoryError) as caught:
                repository.load_turns("session_1", 10, 5)
            self.assertEqual(caught.exception.code, ContextErrorCode.CORRUPT_TAIL.value)


def _turn(
    sequence: int,
    turn_id: str,
    content: str,
    role: ConversationRole,
) -> ConversationTurn:
    kind = (
        ConversationTurnKind.NATURAL_INPUT
        if role == ConversationRole.USER
        else ConversationTurnKind.FINAL_ANSWER
    )
    return ConversationTurn(
        schema_version=CONVERSATION_SCHEMA_VERSION,
        session_id="session_1",
        turn_id=turn_id,
        sequence=sequence,
        role=role,
        kind=kind,
        content=content,
        run_id=f"run_{sequence}",
        created_at=f"2026-07-16T00:00:0{sequence}Z",
    )


def _summary(
    version: int,
    summary_id: str,
    previous_summary_id: str | None,
    covered_end_sequence: int,
) -> ConversationSummary:
    return ConversationSummary(
        schema_version=CONVERSATION_SCHEMA_VERSION,
        session_id="session_1",
        summary_id=summary_id,
        version=version,
        covered_start_sequence=1,
        covered_end_sequence=covered_end_sequence,
        content="已确认的中文摘要。",
        estimated_tokens=5,
        previous_summary_id=previous_summary_id,
        source_turn_ids=tuple(
            f"turn_{sequence}" for sequence in range(1, covered_end_sequence + 1)
        ),
        provider="openai",
        model="model",
        created_at=f"2026-07-16T00:00:0{version}Z",
    )


if __name__ == "__main__":
    unittest.main()
