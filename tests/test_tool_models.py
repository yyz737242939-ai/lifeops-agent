from __future__ import annotations

import unittest

from app.tools.models import (
    ExecutionEvidence,
    GuardrailAction,
    GuardrailDecision,
    GuardrailStage,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolError,
    ToolResult,
    ToolRisk,
)


_EMPTY_OBJECT_SCHEMA = {"type": "object", "properties": {}}


class ToolModelsTest(unittest.TestCase):
    def test_definition_is_handler_independent(self) -> None:
        definition = ToolDefinition(
            name="research.sources_read",
            description="Read trusted research sources.",
            input_schema=_EMPTY_OBJECT_SCHEMA,
            output_schema=_EMPTY_OBJECT_SCHEMA,
            effect=ToolEffect.EXTERNAL_READ,
            risk=ToolRisk.LOW,
        )

        self.assertEqual(definition.effect, ToolEffect.EXTERNAL_READ)
        self.assertFalse(hasattr(definition, "handler"))

    def test_definition_rejects_invalid_required_schema_field(self) -> None:
        with self.assertRaises(ValueError):
            ToolDefinition(
                name="research.sources_read",
                description="Read trusted research sources.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": ["source_id"],
                },
                output_schema=_EMPTY_OBJECT_SCHEMA,
                effect=ToolEffect.EXTERNAL_READ,
                risk=ToolRisk.LOW,
            )

    def test_definition_rejects_duplicate_skill_bindings(self) -> None:
        with self.assertRaises(ValueError):
            ToolDefinition(
                name="research.sources_read",
                description="Read trusted research sources.",
                input_schema=_EMPTY_OBJECT_SCHEMA,
                output_schema=_EMPTY_OBJECT_SCHEMA,
                effect=ToolEffect.EXTERNAL_READ,
                risk=ToolRisk.LOW,
                skill_ids=("research", "research"),
            )

    def test_failed_result_requires_structured_error(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult(
                call_id="call_1",
                tool_name="research.sources_read",
                status=ToolCallStatus.FAILED,
            )

        result = ToolResult(
            call_id="call_1",
            tool_name="research.sources_read",
            status=ToolCallStatus.FAILED,
            error=ToolError("provider_failed", "Provider unavailable.", True),
        )
        self.assertTrue(result.error and result.error.retryable)

    def test_success_result_can_carry_execution_evidence(self) -> None:
        evidence = ExecutionEvidence(
            evidence_type="source_response",
            summary="One source response was validated.",
            reference="artifact://source-1",
        )
        result = ToolResult(
            call_id="call_1",
            tool_name="research.sources_read",
            status=ToolCallStatus.SUCCEEDED,
            output={"count": 1},
            evidence=(evidence,),
        )
        self.assertEqual(result.evidence, (evidence,))

    def test_guardrail_summary_does_not_store_raw_arguments(self) -> None:
        decision = GuardrailDecision(
            action=GuardrailAction.ALLOW,
            stage=GuardrailStage.PRE_EXECUTION,
            reason_code="allowed",
            reason="All deterministic checks passed.",
            tool_name="research.sources_read",
        )
        self.assertNotIn("arguments", decision.__dict__)
        self.assertNotIn("daily-papers", repr(decision))


if __name__ == "__main__":
    unittest.main()
