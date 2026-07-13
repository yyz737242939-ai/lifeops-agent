from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.executor.models import ExecutorStatus, ExecutorStopReason, FinalAnswerDecision, ToolActionDecision
from app.executor.service import ReactExecutor
from app.runtime.models import RuntimeRequest
from app.tools.models import (
    AllowedToolSet,
    ConfirmedAction,
    ExecutionEvidence,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.executor_fakes import FakeActionConfirmationProvider, FakeExecutorModelClient


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}
_OUTPUT_SCHEMA = {"type": "object", "properties": {}}


class ExecutorConfirmationTest(unittest.TestCase):
    def test_write_without_confirmation_stops_before_handler(self) -> None:
        calls: list[ToolCall] = []
        call = _call("call_1", "one")

        result = ReactExecutor(
            FakeExecutorModelClient([ToolActionDecision(call)])
        ).execute(_request(), (), _allowed(), _runtime(calls))

        self.assertEqual(result.status, ExecutorStatus.STOPPED)
        self.assertEqual(
            result.stop_reason, ExecutorStopReason.CONFIRMATION_REQUIRED
        )
        self.assertEqual(calls, [])

    def test_exact_confirmed_action_allows_write_with_evidence(self) -> None:
        calls: list[ToolCall] = []
        call = _call("call_1", "one")
        provider = FakeActionConfirmationProvider(
            ConfirmedAction.for_call(
                "run_test", call, expires_at=_future_expiry()
            )
        )

        result = ReactExecutor(
            FakeExecutorModelClient(
                [ToolActionDecision(call), FinalAnswerDecision("已保存。")]
            ),
            confirmation_provider=provider,
        ).execute(_request(), (), _allowed(), _runtime(calls))

        self.assertEqual(result.status, ExecutorStatus.COMPLETED)
        self.assertEqual(calls, [call])
        self.assertEqual(len(result.observations[0].evidence), 1)
        self.assertEqual(len(provider.requests), 1)

    def test_read_tool_never_requests_confirmation(self) -> None:
        calls: list[ToolCall] = []
        call = _call("call_1", "one")
        provider = FakeActionConfirmationProvider(None)
        runtime = _runtime(calls, effect=ToolEffect.READ)

        result = ReactExecutor(
            FakeExecutorModelClient(
                [ToolActionDecision(call), FinalAnswerDecision("读取完成。")]
            ),
            confirmation_provider=provider,
        ).execute(_request(), (), _allowed(), runtime)

        self.assertEqual(result.status, ExecutorStatus.COMPLETED)
        self.assertEqual(provider.requests, [])
        self.assertEqual(calls, [call])

    def test_second_write_cannot_reuse_first_confirmation(self) -> None:
        calls: list[ToolCall] = []
        first = _call("call_1", "one")
        second = _call("call_2", "two")
        provider = FakeActionConfirmationProvider(
            ConfirmedAction.for_call(
                "run_test", first, expires_at=_future_expiry()
            )
        )

        result = ReactExecutor(
            FakeExecutorModelClient(
                [ToolActionDecision(first), ToolActionDecision(second)]
            ),
            confirmation_provider=provider,
        ).execute(_request(), (), _allowed(), _runtime(calls))

        self.assertEqual(
            result.stop_reason, ExecutorStopReason.CONFIRMATION_REQUIRED
        )
        self.assertEqual(calls, [first])
        self.assertEqual(len(provider.requests), 2)

    def test_two_writes_receive_two_exact_confirmations(self) -> None:
        calls: list[ToolCall] = []
        first = _call("call_1", "one")
        second = _call("call_2", "two")
        provider = _ApprovingConfirmationProvider()

        result = ReactExecutor(
            FakeExecutorModelClient(
                [
                    ToolActionDecision(first),
                    ToolActionDecision(second),
                    FinalAnswerDecision("已保存两次。"),
                ]
            ),
            confirmation_provider=provider,
        ).execute(_request(), (), _allowed(), _runtime(calls))

        self.assertEqual(result.status, ExecutorStatus.COMPLETED)
        self.assertEqual(calls, [first, second])
        self.assertEqual(provider.call_ids, ["call_1", "call_2"])

    def test_changed_expired_or_cross_run_confirmation_is_rejected(self) -> None:
        call = _call("call_1", "one")
        cases = (
            ConfirmedAction.for_call(
                "another_run", call, expires_at=_future_expiry()
            ),
            ConfirmedAction.for_call(
                "run_test", _call("another_call", "one"), expires_at=_future_expiry()
            ),
            ConfirmedAction.for_call(
                "run_test", _call("call_1", "changed"), expires_at=_future_expiry()
            ),
            ConfirmedAction.for_call(
                "run_test", call, expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            ),
        )
        for confirmation in cases:
            with self.subTest(confirmation=confirmation):
                calls: list[ToolCall] = []
                result = ReactExecutor(
                    FakeExecutorModelClient([ToolActionDecision(call)]),
                    confirmation_provider=FakeActionConfirmationProvider(confirmation),
                ).execute(_request(), (), _allowed(), _runtime(calls))

                self.assertEqual(
                    result.stop_reason,
                    ExecutorStopReason.CONFIRMATION_REQUIRED,
                )
                self.assertEqual(calls, [])


def _runtime(
    calls: list[ToolCall], *, effect: ToolEffect = ToolEffect.WRITE
) -> ToolRuntime:
    definition = ToolDefinition(
        name="general.action",
        description="Execute one action.",
        input_schema=_INPUT_SCHEMA,
        output_schema=_OUTPUT_SCHEMA,
        effect=effect,
        risk=ToolRisk.MEDIUM,
    )

    def handler(call: ToolCall) -> ToolResult:
        calls.append(call)
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            status=ToolCallStatus.SUCCEEDED,
            output={},
            evidence=(
                ExecutionEvidence(
                    evidence_type="saved",
                    summary="The action was saved.",
                ),
            ),
        )

    return ToolRuntime.from_registry(ToolRegistry(((definition, handler),)))


def _call(call_id: str, value: str) -> ToolCall:
    return ToolCall(
        call_id=call_id,
        tool_name="general.action",
        arguments={"value": value},
    )


def _allowed() -> AllowedToolSet:
    return AllowedToolSet(("general.action",))


def _request() -> RuntimeRequest:
    return RuntimeRequest(
        user_input="保存信息",
        session_id="session_test",
        run_id="run_test",
    )


def _future_expiry() -> str:
    return (datetime.now(UTC) + timedelta(minutes=5)).isoformat()


class _ApprovingConfirmationProvider:
    def __init__(self) -> None:
        self.call_ids: list[str] = []

    def confirm(self, run_id, call, tool_definition) -> ConfirmedAction:
        self.call_ids.append(call.call_id)
        return ConfirmedAction.for_call(
            run_id, call, expires_at=_future_expiry()
        )


if __name__ == "__main__":
    unittest.main()
