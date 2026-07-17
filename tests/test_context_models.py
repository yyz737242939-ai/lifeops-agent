from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, fields

from app.context.errors import ContextErrorCode
from app.context.models import (
    ContextAssembly,
    ContextBudget,
    ContextContribution,
    ContextContributionKind,
    ContextDegradation,
    ContextDegradationComponent,
    ContextKindCount,
    ContextKindTokenCount,
    ContextProvenance,
    ContextQuery,
    ContextQueryOrigin,
    ContextReport,
    ContextSummaryOutput,
    ConversationRole,
    ConversationSummary,
    ConversationTurn,
    ConversationTurnKind,
)


class ContextModelsTest(unittest.TestCase):
    def test_public_model_fields_are_frozen(self) -> None:
        expected = {
            ConversationTurn: (
                "schema_version",
                "session_id",
                "turn_id",
                "sequence",
                "role",
                "kind",
                "content",
                "run_id",
                "created_at",
            ),
            ConversationSummary: (
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
            ),
            ContextBudget: (
                "max_total_tokens",
                "max_recent_turns",
                "max_summary_tokens",
                "max_profile_tokens",
                "max_memory_items",
                "max_memory_tokens",
                "max_current_input_tokens",
            ),
            ContextQuery: ("text", "origin", "session_id", "run_id", "turn_id"),
            ContextContribution: (
                "kind",
                "source",
                "content",
                "estimated_tokens",
                "provenance",
            ),
            ContextAssembly: (
                "assembly_id",
                "session_id",
                "run_id",
                "turn_id",
                "query",
                "contributions",
                "estimated_total_tokens",
                "report",
            ),
        }
        for model, field_names in expected.items():
            with self.subTest(model=model.__name__):
                self.assertEqual(tuple(item.name for item in fields(model)), field_names)
                self.assertTrue(model.__dataclass_params__.frozen)

    def test_turn_and_summary_enforce_visible_conversation_contract(self) -> None:
        turn = _turn()
        summary = _summary()

        self.assertEqual(turn.role, ConversationRole.USER)
        self.assertEqual(summary.source_turn_ids, ("turn_1",))
        with self.assertRaises(FrozenInstanceError):
            turn.content = "changed"  # type: ignore[misc]
        with self.assertRaises(ValueError):
            ConversationTurn(
                1,
                "session_1",
                "turn_1",
                1,
                ConversationRole.USER,
                ConversationTurnKind.FINAL_ANSWER,
                "content",
                "run_1",
                "2026-07-16T00:00:00Z",
            )
        with self.assertRaises(ValueError):
            ConversationSummary(
                1,
                "session_1",
                "summary_1",
                1,
                2,
                1,
                "summary",
                10,
                None,
                ("turn_1",),
                "openai",
                "model",
                "2026-07-16T00:00:00Z",
            )

    def test_query_contribution_assembly_and_content_free_report_are_typed(self) -> None:
        query = _query()
        contribution = ContextContribution(
            kind=ContextContributionKind.CURRENT_INPUT,
            source="conversation.current_input",
            content="继续完成计划。",
            estimated_tokens=4,
            provenance=ContextProvenance(
                reference="conversation://session_1/turn_1",
                attributes=(("turn_id", "turn_1"), ("sequence", "1")),
            ),
        )
        report = _report()
        assembly = ContextAssembly(
            assembly_id="assembly_1",
            session_id="session_1",
            run_id="run_1",
            turn_id="turn_1",
            query=query,
            contributions=(contribution,),
            estimated_total_tokens=4,
            report=report,
        )

        self.assertEqual(assembly.report.assembly_id, assembly.assembly_id)
        self.assertFalse(hasattr(report, "content"))
        self.assertFalse(hasattr(report, "contributions"))
        self.assertEqual(
            ContextSummaryOutput("summary", "openai", "model").provider,
            "openai",
        )
        with self.assertRaises(ValueError):
            ContextAssembly(
                "assembly_2",
                "session_1",
                "run_1",
                "turn_1",
                query,
                (),
                0,
                report,
            )

    def test_report_metrics_and_degrade_codes_are_content_free_and_unique(self) -> None:
        report = _report()
        self.assertEqual(report.memory_candidate_count, 0)
        self.assertEqual(
            report.degradations[0].error_code,
            ContextErrorCode.HISTORY_READ_FAILED,
        )
        with self.assertRaises(ValueError):
            ContextReport(
                assembly_id="assembly_1",
                selected_turn_count=0,
                summary_version=None,
                summary_covered_range=None,
                profile_included=False,
                memory_candidate_count=0,
                memory_selected_count=0,
                per_kind_estimated_tokens=(
                    ContextKindTokenCount(ContextContributionKind.CURRENT_INPUT, 1),
                    ContextKindTokenCount(ContextContributionKind.CURRENT_INPUT, 1),
                ),
                trimmed_counts=(),
                degradations=(),
                created_at="2026-07-16T00:00:00Z",
            )


def _turn() -> ConversationTurn:
    return ConversationTurn(
        schema_version=1,
        session_id="session_1",
        turn_id="turn_1",
        sequence=1,
        role=ConversationRole.USER,
        kind=ConversationTurnKind.NATURAL_INPUT,
        content="记住刚才的上下文。",
        run_id="run_1",
        created_at="2026-07-16T00:00:00Z",
    )


def _summary() -> ConversationSummary:
    return ConversationSummary(
        schema_version=1,
        session_id="session_1",
        summary_id="summary_1",
        version=1,
        covered_start_sequence=1,
        covered_end_sequence=1,
        content="用户希望保持对话连续性。",
        estimated_tokens=8,
        previous_summary_id=None,
        source_turn_ids=("turn_1",),
        provider="openai",
        model="model",
        created_at="2026-07-16T00:00:00Z",
    )


def _query() -> ContextQuery:
    return ContextQuery(
        text="继续完成计划。",
        origin=ContextQueryOrigin.CURRENT_USER_GOAL,
        session_id="session_1",
        run_id="run_1",
        turn_id="turn_1",
    )


def _report() -> ContextReport:
    return ContextReport(
        assembly_id="assembly_1",
        selected_turn_count=0,
        summary_version=None,
        summary_covered_range=None,
        profile_included=False,
        memory_candidate_count=0,
        memory_selected_count=0,
        per_kind_estimated_tokens=(
            ContextKindTokenCount(ContextContributionKind.CURRENT_INPUT, 4),
        ),
        trimmed_counts=(
            ContextKindCount(ContextContributionKind.CONVERSATION_TURN, 0),
        ),
        degradations=(
            ContextDegradation(
                ContextDegradationComponent.CONVERSATION_HISTORY,
                ContextErrorCode.HISTORY_READ_FAILED,
            ),
        ),
        created_at="2026-07-16T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
