from __future__ import annotations

import unittest

from app.tools.errors import ToolGatewayError
from app.tools.gateway import ToolGateway
from app.tools.models import (
    AllowedToolSet,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from tests.helpers import confirmed_action


_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string", "minLength": 1}},
    "required": ["value"],
    "additionalProperties": False,
}


def _definition(effect: ToolEffect = ToolEffect.READ) -> ToolDefinition:
    return ToolDefinition(
        name="demo.run",
        description="Run one demo Tool.",
        input_schema=_SCHEMA,
        output_schema=_SCHEMA,
        effect=effect,
        risk=ToolRisk.LOW,
    )


class RecordingTrace:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def append(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        self.events.append((event_type, payload or {}))


class ToolGatewayTest(unittest.TestCase):
    def test_rejects_invalid_gateway_contracts(self) -> None:
        with self.assertRaises(ToolGatewayError):
            ToolGateway(object())  # type: ignore[arg-type]

    def test_denied_call_never_reaches_handler(self) -> None:
        called = False

        def handler(call: ToolCall) -> ToolResult:
            nonlocal called
            called = True
            return _success(call)

        gateway = ToolGateway(ToolRegistry([(_definition(), handler)]))

        result = gateway.execute(
            ToolCall("call_1", "demo.run", {"value": "ok"}),
            AllowedToolSet(),
        )

        self.assertEqual(result.status, ToolCallStatus.DENIED)
        self.assertFalse(called)

    def test_success_runs_pre_handler_post_and_emits_safe_events(self) -> None:
        trace = RecordingTrace()
        gateway = ToolGateway(ToolRegistry([(_definition(), _success)]))

        result = gateway.execute(
            ToolCall("call_1", "demo.run", {"value": "secret"}),
            AllowedToolSet(("demo.run",)),
            trace=trace,
        )

        self.assertEqual(result.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(
            [event_type for event_type, _ in trace.events],
            [
                "tool.call.requested",
                "tool.guardrail.decided",
                "tool.guardrail.decided",
                "tool.call.completed",
            ],
        )
        self.assertNotIn("secret", str(trace.events))
        expected_fields = {
            "tool.call.requested": {"call_id", "tool_name"},
            "tool.guardrail.decided": {
                "stage",
                "action",
                "reason_code",
                "tool_name",
            },
            "tool.call.completed": {
                "call_id",
                "tool_name",
                "status",
                "evidence_count",
            },
        }
        for event_type, payload in trace.events:
            self.assertEqual(set(payload), expected_fields[event_type])

    def test_write_confirmation_and_evidence_are_enforced(self) -> None:
        gateway = ToolGateway(
            ToolRegistry([(_definition(ToolEffect.WRITE), _success)])
        )
        call = ToolCall("call_1", "demo.run", {"value": "ok"})

        confirmation = gateway.execute(call, AllowedToolSet(("demo.run",)))
        missing_evidence = gateway.execute(
            call,
            AllowedToolSet(("demo.run",)),
            confirmation=confirmed_action(call),
            run_id="run_test",
        )

        self.assertEqual(
            confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION
        )
        self.assertEqual(missing_evidence.status, ToolCallStatus.FAILED)
        self.assertEqual(
            missing_evidence.error and missing_evidence.error.code,
            "write_evidence_missing",
        )

    def test_handler_exception_and_invalid_result_are_normalized(self) -> None:
        def failing(call: ToolCall) -> ToolResult:
            raise RuntimeError("secret provider detail")

        exception_gateway = ToolGateway(ToolRegistry([(_definition(), failing)]))
        invalid_gateway = ToolGateway(
            ToolRegistry([(_definition(), lambda _: "bad")])  # type: ignore[arg-type,return-value]
        )
        call = ToolCall("call_1", "demo.run", {"value": "ok"})
        allowed = AllowedToolSet(("demo.run",))

        failed = exception_gateway.execute(call, allowed)
        invalid = invalid_gateway.execute(call, allowed)

        self.assertEqual(failed.error and failed.error.code, "tool_handler_failed")
        self.assertNotIn("secret", failed.error.message if failed.error else "")
        self.assertEqual(
            invalid.error and invalid.error.code, "tool_handler_invalid_result"
        )

    def test_invalid_success_output_is_normalized(self) -> None:
        invalid_output = ToolResult(
            call_id="call_1",
            tool_name="demo.run",
            status=ToolCallStatus.SUCCEEDED,
            output={"value": ""},
        )
        gateway = ToolGateway(
            ToolRegistry([(_definition(), lambda _: invalid_output)])
        )

        result = gateway.execute(
            ToolCall("call_1", "demo.run", {"value": "ok"}),
            AllowedToolSet(("demo.run",)),
        )

        self.assertEqual(result.status, ToolCallStatus.FAILED)
        self.assertEqual(result.error and result.error.code, "output_invalid")


def _success(call: ToolCall) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.SUCCEEDED,
        output={"value": "ok"},
    )


if __name__ == "__main__":
    unittest.main()
