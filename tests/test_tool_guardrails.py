from __future__ import annotations

import unittest

from app.tools.guardrails import evaluate_post_execution, evaluate_pre_execution
from app.tools.models import (
    AllowedToolSet,
    ConfirmedAction,
    ExecutionEvidence,
    GuardrailAction,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolError,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from tests.helpers import confirmed_action


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string", "minLength": 1}},
    "required": ["title"],
    "additionalProperties": False,
}
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"saved": {"type": "boolean"}},
    "required": ["saved"],
    "additionalProperties": False,
}


def _definition(effect: ToolEffect = ToolEffect.READ) -> ToolDefinition:
    return ToolDefinition(
        name="tasks.save",
        description="Save one task.",
        input_schema=_INPUT_SCHEMA,
        output_schema=_OUTPUT_SCHEMA,
        effect=effect,
        risk=ToolRisk.LOW,
    )


def _handler(call: ToolCall) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.SUCCEEDED,
        output={"saved": True},
    )


class ToolGuardrailsTest(unittest.TestCase):
    def test_pre_denies_unregistered_and_policy_disallowed_tools(self) -> None:
        call = ToolCall("call_1", "tasks.save", {"title": "Run"})
        unregistered = evaluate_pre_execution(
            call,
            AllowedToolSet(("tasks.save",)),
            ToolRegistry(),
        )
        disallowed = evaluate_pre_execution(
            call,
            AllowedToolSet(),
            ToolRegistry([(_definition(), _handler)]),
        )

        self.assertEqual(unregistered.reason_code, "tool_not_registered")
        self.assertEqual(disallowed.reason_code, "tool_not_allowed")

    def test_write_requires_confirmation_bound_to_exact_action(self) -> None:
        registry = ToolRegistry([(_definition(ToolEffect.WRITE), _handler)])
        allowed_tools = AllowedToolSet(("tasks.save",))
        call = ToolCall("call_1", "tasks.save", {"title": "Run"})

        missing = evaluate_pre_execution(call, allowed_tools, registry)
        wrong_call = ToolCall("call_1", "memory.save", {"title": "Run"})
        wrong = evaluate_pre_execution(
            call,
            allowed_tools,
            registry,
            confirmation=confirmed_action(wrong_call),
            run_id="run_test",
        )
        confirmed = evaluate_pre_execution(
            call,
            allowed_tools,
            registry,
            confirmation=confirmed_action(call),
            run_id="run_test",
        )
        changed_arguments = evaluate_pre_execution(
            ToolCall("call_1", "tasks.save", {"title": "Changed"}),
            allowed_tools,
            registry,
            confirmation=confirmed_action(call),
            run_id="run_test",
        )
        other_run = evaluate_pre_execution(
            call,
            allowed_tools,
            registry,
            confirmation=confirmed_action(call),
            run_id="run_other",
        )
        expired = evaluate_pre_execution(
            call,
            allowed_tools,
            registry,
            confirmation=ConfirmedAction.for_call(
                "run_test", call, expires_at="2000-01-01T00:00:00+00:00"
            ),
            run_id="run_test",
        )

        self.assertEqual(missing.action, GuardrailAction.REQUIRES_CONFIRMATION)
        self.assertEqual(wrong.action, GuardrailAction.REQUIRES_CONFIRMATION)
        self.assertEqual(confirmed.action, GuardrailAction.ALLOW)
        self.assertEqual(changed_arguments.action, GuardrailAction.REQUIRES_CONFIRMATION)
        self.assertEqual(other_run.action, GuardrailAction.REQUIRES_CONFIRMATION)
        self.assertEqual(expired.action, GuardrailAction.REQUIRES_CONFIRMATION)

    def test_pre_rejects_invalid_arguments_without_recording_raw_values(self) -> None:
        registry = ToolRegistry([(_definition(), _handler)])
        allowed_tools = AllowedToolSet(("tasks.save",))
        call = ToolCall("call_1", "tasks.save", {"title": ""})

        decision = evaluate_pre_execution(call, allowed_tools, registry)

        self.assertEqual(decision.reason_code, "arguments_invalid")
        self.assertNotIn("Run", str(decision))

    def test_post_rejects_identity_failure_and_invalid_output(self) -> None:
        registry = ToolRegistry([(_definition(), _handler)])
        call = ToolCall("call_1", "tasks.save", {"title": "Run"})
        mismatch = ToolResult(
            call_id="call_other",
            tool_name="tasks.save",
            status=ToolCallStatus.SUCCEEDED,
            output={"saved": True},
        )
        failed = ToolResult(
            call_id="call_1",
            tool_name="tasks.save",
            status=ToolCallStatus.FAILED,
            error=ToolError("provider_failed", "Provider failed."),
        )
        invalid = ToolResult(
            call_id="call_1",
            tool_name="tasks.save",
            status=ToolCallStatus.SUCCEEDED,
            output={"saved": "yes"},
        )

        self.assertEqual(
            evaluate_post_execution(call, mismatch, registry).reason_code,
            "result_identity_mismatch",
        )
        self.assertEqual(
            evaluate_post_execution(call, failed, registry).reason_code,
            "tool_not_succeeded",
        )
        self.assertEqual(
            evaluate_post_execution(call, invalid, registry).reason_code,
            "output_invalid",
        )

    def test_write_success_requires_evidence(self) -> None:
        registry = ToolRegistry([(_definition(ToolEffect.WRITE), _handler)])
        call = ToolCall("call_1", "tasks.save", {"title": "Run"})
        without_evidence = ToolResult(
            call_id="call_1",
            tool_name="tasks.save",
            status=ToolCallStatus.SUCCEEDED,
            output={"saved": True},
        )
        with_evidence = ToolResult(
            call_id="call_1",
            tool_name="tasks.save",
            status=ToolCallStatus.SUCCEEDED,
            output={"saved": True},
            evidence=(ExecutionEvidence("write_effect", "Task row created."),),
        )

        self.assertEqual(
            evaluate_post_execution(call, without_evidence, registry).reason_code,
            "write_evidence_missing",
        )
        self.assertEqual(
            evaluate_post_execution(call, with_evidence, registry).action,
            GuardrailAction.ALLOW,
        )


if __name__ == "__main__":
    unittest.main()
