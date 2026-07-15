from __future__ import annotations

import unittest

from app.executor.models import (
    ExecutorContextContribution,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    ToolActionDecision,
)
from app.executor.service import ReactExecutor
from app.runtime.models import RuntimeRequest
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
from app.tools.runtime import ToolRuntime
from tests.executor_fakes import (
    FakeExecutorContextProvider,
    FakeExecutorModelClient,
)


_EMPTY_SCHEMA = {"type": "object", "properties": {}}


class ExecutorGatewayIntegrationTest(unittest.TestCase):
    def test_filtered_catalog_and_gateway_are_the_only_execution_path(self) -> None:
        allowed_call = ToolCall(call_id="call_1", tool_name="general.allowed")
        handler_calls: list[ToolCall] = []
        runtime = _runtime(
            (
                _tool("general.allowed", handler_calls),
                _tool("general.hidden", []),
            )
        )
        model = FakeExecutorModelClient(
            [ToolActionDecision(allowed_call), FinalAnswerDecision("完成。")]
        )

        result = ReactExecutor(model).execute(
            _request(),
            (),
            AllowedToolSet(("general.allowed",)),
            runtime,
        )

        self.assertEqual(result.status, ExecutorStatus.COMPLETED)
        self.assertEqual(handler_calls, [allowed_call])
        self.assertEqual(
            tuple(item["name"] for item in model.inputs[0].tool_catalog),
            ("general.allowed",),
        )

    def test_catalog_excluded_call_is_denied_without_reaching_handler(self) -> None:
        hidden_calls: list[ToolCall] = []
        call = ToolCall(call_id="call_1", tool_name="general.hidden")
        runtime = _runtime(
            (
                _tool("general.allowed", []),
                _tool("general.hidden", hidden_calls),
            )
        )

        result = ReactExecutor(
            FakeExecutorModelClient([ToolActionDecision(call)])
        ).execute(
            _request(),
            (),
            AllowedToolSet(("general.allowed",)),
            runtime,
        )

        self.assertEqual(result.stop_reason, ExecutorStopReason.SAFETY_DENIED)
        self.assertEqual(hidden_calls, [])
        self.assertEqual(result.last_tool_result.status, ToolCallStatus.DENIED)

    def test_multiple_calls_reuse_one_execution_scope(self) -> None:
        handler_calls: list[ToolCall] = []
        first = ToolCall(call_id="call_1", tool_name="general.read")
        second = ToolCall(call_id="call_2", tool_name="general.read")
        runtime = _runtime((_tool("general.read", handler_calls),))

        result = ReactExecutor(
            FakeExecutorModelClient(
                [
                    ToolActionDecision(first),
                    ToolActionDecision(second),
                    FinalAnswerDecision("完成两次调用。"),
                ]
            )
        ).execute(
            _request(),
            (),
            AllowedToolSet(("general.read",)),
            runtime,
        )

        self.assertEqual(handler_calls, [first, second])
        self.assertEqual(len(result.observations), 2)

    def test_separate_execution_scopes_do_not_share_handler_state(self) -> None:
        first_calls: list[ToolCall] = []
        second_calls: list[ToolCall] = []
        call = ToolCall(call_id="call_1", tool_name="general.read")
        allowed = AllowedToolSet(("general.read",))

        first = ReactExecutor(
            FakeExecutorModelClient(
                [ToolActionDecision(call), FinalAnswerDecision("first")]
            )
        ).execute(
            _request("run_1"),
            (),
            allowed,
            _runtime((_tool("general.read", first_calls),)),
        )
        second = ReactExecutor(
            FakeExecutorModelClient(
                [ToolActionDecision(call), FinalAnswerDecision("second")]
            )
        ).execute(
            _request("run_2"),
            (),
            allowed,
            _runtime((_tool("general.read", second_calls),)),
        )

        self.assertEqual(first.run_id, "run_1")
        self.assertEqual(second.run_id, "run_2")
        self.assertEqual(len(first_calls), 1)
        self.assertEqual(len(second_calls), 1)

    def test_input_provider_failure_stops_before_model_or_gateway(self) -> None:
        model = FakeExecutorModelClient([FinalAnswerDecision("unused")])
        executor = ReactExecutor(model, context_provider=_ExplodingContextProvider())

        result = executor.execute(
            _request(), (), AllowedToolSet(), _runtime(())
        )

        self.assertEqual(result.status, ExecutorStatus.FAILED)
        self.assertEqual(
            result.stop_reason, ExecutorStopReason.INPUT_PROVIDER_FAILED
        )
        self.assertEqual(result.error_code, "executor_input_provider_failed")
        self.assertEqual(model.inputs, [])
        self.assertNotIn("private-context-path", repr(result))


def _tool(name: str, calls: list[ToolCall]):
    definition = ToolDefinition(
        name=name,
        description=f"Execute {name}.",
        input_schema=_EMPTY_SCHEMA,
        output_schema=_EMPTY_SCHEMA,
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
    )

    def handler(call: ToolCall) -> ToolResult:
        calls.append(call)
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            status=ToolCallStatus.SUCCEEDED,
            output={},
        )

    return definition, handler


def _runtime(tools) -> ToolRuntime:
    return ToolRuntime.from_registry(ToolRegistry(tools))


def _request(run_id: str = "run_test") -> RuntimeRequest:
    return RuntimeRequest(
        user_input="执行请求",
        session_id="session_test",
        run_id=run_id,
    )


class _ExplodingContextProvider:
    def load(
        self, request: RuntimeRequest, *, plan_step=None
    ) -> tuple[ExecutorContextContribution, ...]:
        raise RuntimeError("private-context-path")


if __name__ == "__main__":
    unittest.main()
