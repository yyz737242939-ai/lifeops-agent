from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.context.adapters import FakeMemoryRetriever, FakeProfileProvider
from app.context.assembler import ContextAssembler
from app.context.errors import ContextContractError, ContextErrorCode
from app.context.models import (
    ContextBudget,
    ContextContribution,
    ContextContributionKind,
    ContextProvenance,
    ContextQuery,
    ContextQueryOrigin,
    ContextSummaryOutput,
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.repository import JsonlConversationRepository
from app.context.summarizer import FakeContextSummarizer
from app.context.summary_service import RollingSummaryService


class ContextAssemblerTest(unittest.TestCase):
    def test_summary_recent_and_current_are_ordered_deduplicated_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")
            turns = tuple(_turn(index, content=f"visible {index}") for index in range(1, 6))
            for turn in turns:
                repository.append_turn(turn)
            summarizer = FakeContextSummarizer(
                (ContextSummaryOutput("older summary", "fake", "model"),)
            )
            assembler = _assembler(repository, summarizer)

            assembly = assembler.assemble(_query(turns[-1]), _budget(max_recent_turns=2))

            self.assertEqual(
                tuple(item.kind for item in assembly.contributions),
                (
                    ContextContributionKind.CONVERSATION_SUMMARY,
                    ContextContributionKind.CONVERSATION_TURN,
                    ContextContributionKind.CONVERSATION_TURN,
                    ContextContributionKind.CURRENT_INPUT,
                ),
            )
            self.assertEqual(
                tuple(item.content for item in assembly.contributions),
                ("older summary", "visible 3", "visible 4", "visible 5"),
            )
            self.assertEqual(sum(item.content == "visible 5" for item in assembly.contributions), 1)
            self.assertEqual(assembly.estimated_total_tokens, sum(item.estimated_tokens for item in assembly.contributions))
            self.assertEqual(assembly.report.summary_version, 1)
            self.assertEqual(assembly.report.summary_covered_range, (1, 2))
            self.assertEqual(assembly.report.selected_turn_count, 2)
            self.assertFalse(hasattr(assembly.report, "content"))
            self.assertEqual(len(summarizer.calls), 1)

    def test_profile_and_memory_fake_slots_use_caps_order_and_reference_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")
            current = _turn(1, content="current")
            repository.append_turn(current)
            profile = _external(ContextContributionKind.PROFILE, "profile", "profile://fixed")
            duplicate = _external(ContextContributionKind.MEMORY, "memory one", "memory://1")
            profile_provider = FakeProfileProvider(profile)
            memory_retriever = FakeMemoryRetriever((duplicate, duplicate))
            assembler = _assembler(
                repository,
                FakeContextSummarizer(()),
                profile_provider=profile_provider,
                memory_retriever=memory_retriever,
            )

            assembly = assembler.assemble(_query(current), _budget())

            self.assertEqual(
                tuple(item.kind for item in assembly.contributions),
                (
                    ContextContributionKind.PROFILE,
                    ContextContributionKind.MEMORY,
                    ContextContributionKind.CURRENT_INPUT,
                ),
            )
            self.assertEqual(profile_provider.load_count, 1)
            self.assertEqual(memory_retriever.calls, [(_query(current), 3, 20)])
            self.assertEqual(assembly.report.memory_candidate_count, 2)
            self.assertEqual(assembly.report.memory_selected_count, 1)
            self.assertTrue(assembly.report.profile_included)

    def test_current_and_recent_priority_trim_profile_memory_and_older_turns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")
            turns = (
                _turn(1, content="12345678"),
                _turn(2, content="abcdefgh"),
                _turn(3, content="current8"),
            )
            for turn in turns:
                repository.append_turn(turn)
            assembler = _assembler(
                repository,
                FakeContextSummarizer(()),
                profile_provider=FakeProfileProvider(
                    _external(ContextContributionKind.PROFILE, "profile8", "profile://fixed")
                ),
                memory_retriever=FakeMemoryRetriever(
                    (_external(ContextContributionKind.MEMORY, "memory88", "memory://1"),)
                ),
            )
            budget = ContextBudget(4, 2, 0, 4, 2, 4, 2)

            assembly = assembler.assemble(_query(turns[-1]), budget)

            self.assertEqual(
                tuple(item.kind for item in assembly.contributions),
                (
                    ContextContributionKind.CONVERSATION_TURN,
                    ContextContributionKind.CURRENT_INPUT,
                ),
            )
            self.assertEqual(assembly.contributions[0].content, "abcdefgh")
            self.assertLessEqual(assembly.estimated_total_tokens, budget.max_total_tokens)
            self.assertFalse(assembly.report.profile_included)
            self.assertEqual(assembly.report.memory_selected_count, 0)

    def test_provider_failures_degrade_without_content_or_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")
            current = _turn(1, content="current")
            repository.append_turn(current)
            assembler = _assembler(
                repository,
                FakeContextSummarizer(()),
                profile_provider=_ExplodingProfile(),
                memory_retriever=_ExplodingMemory(),
            )

            assembly = assembler.assemble(_query(current), _budget())

            self.assertEqual(
                tuple(item.kind for item in assembly.contributions),
                (ContextContributionKind.CURRENT_INPUT,),
            )
            self.assertEqual(
                {item.error_code for item in assembly.report.degradations},
                {
                    ContextErrorCode.PROFILE_PROVIDER_FAILED,
                    ContextErrorCode.MEMORY_PROVIDER_FAILED,
                },
            )
            self.assertFalse(hasattr(assembly, "allowed_tools"))
            self.assertFalse(hasattr(assembly, "policy"))

    def test_oversized_current_input_fails_before_summary_or_providers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonlConversationRepository(Path(directory) / "conversations")
            current = _turn(1, content="x" * 20)
            repository.append_turn(current)
            profile = FakeProfileProvider(None)
            memory = FakeMemoryRetriever(())
            summarizer = FakeContextSummarizer(())
            assembler = _assembler(
                repository,
                summarizer,
                profile_provider=profile,
                memory_retriever=memory,
            )
            with self.assertRaises(ContextContractError) as caught:
                assembler.assemble(
                    _query(current),
                    ContextBudget(10, 2, 4, 0, 0, 0, 2),
                )
            self.assertEqual(caught.exception.code, ContextErrorCode.INPUT_TOO_LARGE.value)
            self.assertEqual(profile.load_count, 0)
            self.assertEqual(memory.calls, [])
            self.assertEqual(summarizer.calls, [])


class _ExplodingProfile:
    def load_profile(self):
        raise RuntimeError("private profile failure")


class _ExplodingMemory:
    def search(self, query, max_items, max_tokens):
        raise RuntimeError("private memory failure")


def _assembler(
    repository,
    summarizer,
    *,
    profile_provider=None,
    memory_retriever=None,
) -> ContextAssembler:
    return ContextAssembler(
        repository,
        RollingSummaryService(
            repository,
            summarizer,
            id_factory=lambda prefix: f"{prefix}_1",
            clock=lambda: "2026-07-16T00:00:00Z",
        ),
        profile_provider=profile_provider,
        memory_retriever=memory_retriever,
        id_factory=lambda prefix: f"{prefix}_1",
        clock=lambda: "2026-07-16T00:00:00Z",
    )


def _budget(*, max_recent_turns: int = 4) -> ContextBudget:
    return ContextBudget(100, max_recent_turns, 20, 20, 3, 20, 40)


def _turn(sequence: int, *, content: str) -> ConversationTurn:
    role = ConversationRole.USER if sequence % 2 else ConversationRole.ASSISTANT
    return ConversationTurn(
        schema_version=1,
        session_id="session_1",
        turn_id=f"turn_{sequence}",
        sequence=sequence,
        role=role,
        kind=(
            ConversationTurnKind.NATURAL_INPUT
            if role == ConversationRole.USER
            else ConversationTurnKind.FINAL_ANSWER
        ),
        content=content,
        run_id=f"run_{sequence}",
        created_at=f"2026-07-16T00:00:{sequence:02d}Z",
    )


def _query(turn: ConversationTurn) -> ContextQuery:
    return ContextQuery(
        text=turn.content,
        origin=ContextQueryOrigin.CURRENT_USER_GOAL,
        session_id=turn.session_id,
        run_id=turn.run_id,
        turn_id=turn.turn_id,
    )


def _external(
    kind: ContextContributionKind,
    content: str,
    reference: str,
) -> ContextContribution:
    return ContextContribution(
        kind=kind,
        source=kind.value,
        content=content,
        estimated_tokens=2,
        provenance=ContextProvenance(reference),
    )


if __name__ == "__main__":
    unittest.main()
