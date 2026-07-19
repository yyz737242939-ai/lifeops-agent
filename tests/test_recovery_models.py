from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path

from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    ExecutionActionFeedback,
    ExecutionFeedback,
    ExecutionFeedbackEvidence,
    ExecutionOutcome,
    ExecutionPath,
    FeedbackOverallStatus,
    FinalAnswerValidation,
    RecoveryContext,
    RecoveryOutputMode,
    RecoveryResult,
    RecoveryStopPoint,
)
from app.tools.models import ToolEffect


class RecoveryModelsTest(unittest.TestCase):
    def test_feedback_models_are_immutable_safe_and_source_linked(self) -> None:
        evidence = ExecutionFeedbackEvidence(
            "write_effect", "A source was saved.", "source/ref_1", "call_1", 0
        )
        action = ExecutionActionFeedback(
            1,
            "execinv_1",
            "span_1",
            "call_1",
            "research.save_source",
            ToolEffect.WRITE,
            ExecutionOutcome.SUCCEEDED,
            evidence=(evidence,),
        )
        feedback = ExecutionFeedback(
            "feedback_1",
            "trace_1",
            "run_1",
            "session_1",
            ExecutionPath.DIRECT,
            "Save one source.",
            FeedbackOverallStatus.COMPLETED,
            "final_answer",
            None,
            ("execinv_1",),
            (action,),
            (),
            "2026-07-17T00:00:00Z",
        )

        self.assertEqual(action.evidence_refs, ("source/ref_1",))
        self.assertIsNone(feedback.validation)
        self.assertFalse(hasattr(action, "arguments"))
        self.assertFalse(hasattr(action, "output"))
        self.assertFalse(hasattr(feedback, "assistant_text"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            action.call_id = "changed"  # type: ignore[misc]
        with self.assertRaises(ValueError):
            ExecutionFeedbackEvidence("type", "summary", None, "call_1", -1)

    def test_validation_separates_claim_status_from_output_mode(self) -> None:
        valid = FinalAnswerValidation(
            ClaimStatus.VALID, AnswerOutputMode.MODEL, accepted_claim_ids=("claim_1",)
        )
        invalid = FinalAnswerValidation(
            ClaimStatus.INVALID,
            AnswerOutputMode.DETERMINISTIC_FALLBACK,
            ("claim_reference_unknown",),
        )
        self.assertEqual(valid.reason_codes, ())
        self.assertEqual(invalid.claim_status, ClaimStatus.INVALID)
        with self.assertRaises(ValueError):
            FinalAnswerValidation(
                ClaimStatus.INVALID, AnswerOutputMode.MODEL, ("reason",)
            )

    def test_recovery_models_are_read_only_explanation_values(self) -> None:
        context = RecoveryContext(
            "trace_source",
            "run_source",
            "session_1",
            "Explain the stopped run.",
            ExecutionPath.DIRECT,
            RecoveryStopPoint(FeedbackOverallStatus.FAILED, "model_failed"),
            (),
            (),
            (),
            (),
            (),
            (),
            ("Review the input before a new request.",),
            "2026-07-17T00:01:00Z",
        )
        result = RecoveryResult(
            context,
            "The source run stopped before completion.",
            RecoveryOutputMode.DETERMINISTIC,
        )
        self.assertEqual(result.context.source_run_id, "run_source")
        for forbidden in (
            "allowed_tools",
            "confirmation",
            "tool_runtime",
            "tool_call",
        ):
            self.assertFalse(hasattr(context, forbidden))

    def test_pure_recovery_code_has_no_storage_runtime_or_provider_dependency(self) -> None:
        forbidden = (
            "app.storage",
            "app.runtime",
            "app.observability",
            "app.runtime_reporting",
            "langgraph",
            "openai",
            "sqlite3",
        )
        violations: list[str] = []
        for filename in ("models.py", "builder.py", "validator.py", "errors.py"):
            tree = ast.parse(
                (Path("app/recovery") / filename).read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                violations.extend(
                    name
                    for name in names
                    if any(name == item or name.startswith(f"{item}.") for item in forbidden)
                )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
