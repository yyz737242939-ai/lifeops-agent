from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.context.errors import ContextContractError, ContextErrorCode, ContextProviderError
from app.context.models import (
    ContextBudget,
    ContextSummaryOutput,
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.repository import JsonlConversationRepository
from app.context.summarizer import FakeContextSummarizer
from app.context.summary_service import RollingSummaryService


class ContextRollingSummaryTest(unittest.TestCase):
    def test_first_and_incremental_summary_reuse_previous_and_append_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")
            first_fake = FakeContextSummarizer(
                (ContextSummaryOutput("summary one", "fake", "model"),)
            )
            first = RollingSummaryService(
                repository,
                first_fake,
                id_factory=lambda prefix: f"{prefix}_1",
                clock=lambda: "2026-07-16T00:00:01Z",
            ).summarize("session_1", (_turn(1), _turn(2)), _budget())

            self.assertEqual(first.version, 1)
            self.assertEqual((first.covered_start_sequence, first.covered_end_sequence), (1, 2))
            self.assertEqual(first.previous_summary_id, None)
            self.assertEqual(first.source_turn_ids, ("turn_1", "turn_2"))
            self.assertIsNone(first_fake.calls[0][0])

            second_fake = FakeContextSummarizer(
                (ContextSummaryOutput("summary two", "fake", "model"),)
            )
            second = RollingSummaryService(
                repository,
                second_fake,
                id_factory=lambda prefix: f"{prefix}_2",
                clock=lambda: "2026-07-16T00:00:02Z",
            ).summarize("session_1", (_turn(3), _turn(4)), _budget())

            self.assertEqual(second.version, 2)
            self.assertEqual((second.covered_start_sequence, second.covered_end_sequence), (1, 4))
            self.assertEqual(second.previous_summary_id, first.summary_id)
            self.assertEqual(second.source_turn_ids, ("turn_3", "turn_4"))
            self.assertEqual(second_fake.calls[0][0], first)
            self.assertEqual(repository.load_latest_valid_summary("session_1"), second)

    def test_non_contiguous_or_cross_session_input_stops_before_provider(self) -> None:
        invalid = (
            (),
            (_turn(2),),
            (_turn(1), _turn(3)),
            (_turn(1), _turn(2, session_id="other")),
        )
        for turns in invalid:
            with tempfile.TemporaryDirectory() as directory:
                fake = FakeContextSummarizer(
                    (ContextSummaryOutput("unused", "fake", "model"),)
                )
                service = RollingSummaryService(
                    JsonlConversationRepository(Path(directory) / "conversations"),
                    fake,
                )
                with self.subTest(turns=turns), self.assertRaises(ContextContractError):
                    service.summarize("session_1", turns, _budget())
                self.assertEqual(fake.calls, [])

    def test_failed_invalid_or_oversized_output_is_never_persisted(self) -> None:
        summarizers = (
            _FailingSummarizer(),
            _InvalidSummarizer(),
            FakeContextSummarizer(
                (ContextSummaryOutput("x" * 200, "fake", "model"),)
            ),
        )
        expected_codes = (
            ContextErrorCode.SUMMARY_PROVIDER_FAILED,
            ContextErrorCode.SUMMARY_INVALID,
            ContextErrorCode.SUMMARY_TOO_LARGE,
        )
        for summarizer, expected_code in zip(summarizers, expected_codes, strict=True):
            with tempfile.TemporaryDirectory() as directory:
                repository = JsonlConversationRepository(Path(directory) / "conversations")
                service = RollingSummaryService(repository, summarizer)
                with self.subTest(summarizer=type(summarizer).__name__), self.assertRaises(
                    (ContextContractError, ContextProviderError)
                ) as caught:
                    service.summarize("session_1", (_turn(1),), _budget())
                self.assertEqual(caught.exception.code, expected_code.value)
                self.assertIsNone(repository.load_latest_valid_summary("session_1"))


class _FailingSummarizer:
    def summarize(self, previous_summary, contiguous_turns, budget, *, llm_log=None):
        raise ContextProviderError(
            "Safe provider failure.",
            code=ContextErrorCode.SUMMARY_PROVIDER_FAILED,
        )


class _InvalidSummarizer:
    def summarize(self, previous_summary, contiguous_turns, budget, *, llm_log=None):
        return "invalid"


def _budget() -> ContextBudget:
    return ContextBudget(100, 4, 20, 0, 0, 0, 40)


def _turn(sequence: int, *, session_id: str = "session_1") -> ConversationTurn:
    return ConversationTurn(
        schema_version=1,
        session_id=session_id,
        turn_id=f"turn_{sequence}",
        sequence=sequence,
        role=ConversationRole.USER if sequence % 2 else ConversationRole.ASSISTANT,
        kind=(
            ConversationTurnKind.NATURAL_INPUT
            if sequence % 2
            else ConversationTurnKind.FINAL_ANSWER
        ),
        content=f"turn {sequence}",
        run_id=f"run_{sequence}",
        created_at=f"2026-07-16T00:00:{sequence:02d}Z",
    )


if __name__ == "__main__":
    unittest.main()
