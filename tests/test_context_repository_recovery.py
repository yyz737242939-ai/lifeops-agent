from __future__ import annotations

import json
import tempfile
import threading
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
    CONVERSATION_CONCURRENCY_POLICY,
    CONVERSATION_SCHEMA_VERSION,
    CorruptTailPolicy,
    JsonlConversationRepository,
)


class ContextRepositoryRecoveryTest(unittest.TestCase):
    def test_restart_reads_existing_turns_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            writer = JsonlConversationRepository(root)
            writer.append_turn(_turn(1, "turn_1"))
            writer.append_summary(_summary(1, "summary_1", None, 1))

            restarted = JsonlConversationRepository(root)

            self.assertEqual(restarted.load_turns("session_1", 1, 10), (_turn(1, "turn_1"),))
            self.assertEqual(
                restarted.load_latest_valid_summary("session_1"),
                _summary(1, "summary_1", None, 1),
            )

    def test_corrupt_tail_policy_is_explicit_and_fails_closed(self) -> None:
        self.assertEqual(tuple(CorruptTailPolicy), (CorruptTailPolicy.FAIL,))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            repository = JsonlConversationRepository(root)
            repository.append_turn(_turn(1, "turn_1"))
            path = root / "session_1" / "turns.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"partial":')

            with self.assertRaises(ConversationRepositoryError) as caught:
                repository.load_turns("session_1", 10, 10)
            self.assertEqual(caught.exception.code, ContextErrorCode.CORRUPT_TAIL.value)

    def test_turn_append_requires_contiguous_sequence_and_unique_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")

            with self.assertRaises(ConversationRepositoryError) as first:
                repository.append_turn(_turn(2, "turn_2"))
            self.assertEqual(first.exception.code, ContextErrorCode.SEQUENCE_INVALID.value)

            repository.append_turn(_turn(1, "turn_1"))
            for invalid in (_turn(3, "turn_3"), _turn(2, "turn_1")):
                with self.subTest(invalid=invalid), self.assertRaises(
                    ConversationRepositoryError
                ) as caught:
                    repository.append_turn(invalid)
                self.assertEqual(caught.exception.code, ContextErrorCode.SEQUENCE_INVALID.value)

    def test_read_rejects_non_contiguous_persisted_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            path = root / "session_1" / "turns.jsonl"
            path.parent.mkdir(parents=True)
            rows = [_turn_payload(_turn(1, "turn_1")), _turn_payload(_turn(3, "turn_3"))]
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            with self.assertRaises(ConversationRepositoryError) as caught:
                JsonlConversationRepository(root).load_turns("session_1", 10, 10)
            self.assertEqual(caught.exception.code, ContextErrorCode.SEQUENCE_INVALID.value)

    def test_summary_append_requires_contiguous_version_and_previous_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")
            repository.append_summary(_summary(1, "summary_1", None, 1))

            invalid = (
                _summary(3, "summary_3", "summary_1", 3),
                _summary(2, "summary_2", "wrong", 2),
                _summary(2, "summary_1", "summary_1", 2),
                _summary(2, "summary_2", "summary_1", 1),
            )
            for summary in invalid:
                with self.subTest(summary=summary), self.assertRaises(
                    ConversationRepositoryError
                ) as caught:
                    repository.append_summary(summary)
                self.assertEqual(caught.exception.code, ContextErrorCode.SEQUENCE_INVALID.value)

            valid = _summary(2, "summary_2", "summary_1", 2)
            repository.append_summary(valid)
            self.assertEqual(repository.load_latest_valid_summary("session_1"), valid)

    def test_same_process_concurrent_first_append_commits_exactly_one_turn(self) -> None:
        self.assertEqual(
            CONVERSATION_CONCURRENCY_POLICY,
            "process_local_serialized_append",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            repositories = (
                JsonlConversationRepository(root),
                JsonlConversationRepository(root),
            )
            barrier = threading.Barrier(2)
            outcomes: list[str] = []
            outcomes_lock = threading.Lock()

            def append(repository: JsonlConversationRepository, turn_id: str) -> None:
                barrier.wait()
                try:
                    repository.append_turn(_turn(1, turn_id))
                    outcome = "success"
                except ConversationRepositoryError as exc:
                    outcome = exc.code or "missing_code"
                with outcomes_lock:
                    outcomes.append(outcome)

            threads = (
                threading.Thread(target=append, args=(repositories[0], "turn_a")),
                threading.Thread(target=append, args=(repositories[1], "turn_b")),
            )
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertEqual(
                sorted(outcomes),
                [ContextErrorCode.SEQUENCE_INVALID.value, "success"],
            )
            persisted = repositories[0].load_turns("session_1", 1, 10)
            self.assertEqual(len(persisted), 1)


def _turn(sequence: int, turn_id: str) -> ConversationTurn:
    return ConversationTurn(
        schema_version=CONVERSATION_SCHEMA_VERSION,
        session_id="session_1",
        turn_id=turn_id,
        sequence=sequence,
        role=ConversationRole.USER,
        kind=ConversationTurnKind.NATURAL_INPUT,
        content=f"turn {sequence}",
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
        content=f"summary {version}",
        estimated_tokens=3,
        previous_summary_id=previous_summary_id,
        source_turn_ids=tuple(
            f"turn_{sequence}" for sequence in range(1, covered_end_sequence + 1)
        ),
        provider="openai",
        model="model",
        created_at=f"2026-07-16T00:00:0{version}Z",
    )


def _turn_payload(turn: ConversationTurn) -> dict[str, object]:
    return {
        "schema_version": turn.schema_version,
        "session_id": turn.session_id,
        "turn_id": turn.turn_id,
        "sequence": turn.sequence,
        "role": turn.role.value,
        "kind": turn.kind.value,
        "content": turn.content,
        "run_id": turn.run_id,
        "created_at": turn.created_at,
    }


if __name__ == "__main__":
    unittest.main()
