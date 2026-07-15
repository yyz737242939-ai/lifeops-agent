from __future__ import annotations

import unittest

from app.executor.errors import InvalidExecutorModelActionError
from app.executor.graph import (
    ExecutorGraphContext,
    build_executor_graph,
    invoke_executor_graph,
)
from app.executor.models import (
    ExecutionLimits,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    PlanStepExecutionInput,
    ToolActionDecision,
)
from app.executor.state import create_executor_state
from app.runtime.models import RuntimeRequest
from app.tools.models import (
    ToolCall,
    ToolCallStatus,
    ToolError,
    ToolResult,
)
from tests.executor_fakes import FakeExecutorModelClient, FakeExecutorToolGateway


class ExecutorGraphTest(unittest.TestCase):
    def test_executor_graph_is_compiled_without_a_checkpointer(self) -> None:
        self.assertIsNone(build_executor_graph().checkpointer)

    def test_immediate_final_answer_needs_no_tool_even_with_empty_catalog(self) -> None:
        model = FakeExecutorModelClient([FinalAnswerDecision("可以直接回答。")])
        gateway = FakeExecutorToolGateway([])

        state = _invoke(model, gateway)

        self.assertEqual(state["result"].status, ExecutorStatus.COMPLETED)
        self.assertEqual(
            state["result"].stop_reason, ExecutorStopReason.FINAL_ANSWER
        )
        self.assertEqual(state["result"].step_count, 1)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(model.inputs[0].tool_catalog, ())

    def test_success_observation_returns_to_model_before_final_answer(self) -> None:
        call = _call("call_1", "research.search_knowledge")
        tool_result = _result(call, ToolCallStatus.SUCCEEDED, output={"count": 1})
        model = FakeExecutorModelClient(
            [ToolActionDecision(call), FinalAnswerDecision("找到一条记录。")]
        )
        gateway = FakeExecutorToolGateway([tool_result])

        state = _invoke(
            model,
            gateway,
            tool_catalog=({"name": call.tool_name},),
        )

        result = state["result"]
        self.assertEqual(result.status, ExecutorStatus.COMPLETED)
        self.assertEqual(result.step_count, 2)
        self.assertEqual(result.last_tool_result, tool_result)
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(model.inputs[1].observations, result.observations)
        self.assertEqual(model.inputs[1].step_index, 2)

    def test_failed_tool_can_be_observed_before_an_alternate_action(self) -> None:
        first = _call("call_1", "travel.search_places")
        second = _call("call_2", "travel.get_weather")
        failed = _result(
            first,
            ToolCallStatus.FAILED,
            error=ToolError("provider_unavailable", "Provider unavailable.", True),
        )
        succeeded = _result(second, ToolCallStatus.SUCCEEDED, output={"ok": True})
        model = FakeExecutorModelClient(
            [
                ToolActionDecision(first),
                ToolActionDecision(second),
                FinalAnswerDecision("已改用其他工具。"),
            ]
        )
        gateway = FakeExecutorToolGateway([failed, succeeded])

        state = _invoke(model, gateway)

        self.assertEqual(state["result"].status, ExecutorStatus.COMPLETED)
        self.assertEqual(state["result"].step_count, 3)
        self.assertEqual(
            [item.status for item in state["result"].observations],
            [ToolCallStatus.FAILED, ToolCallStatus.SUCCEEDED],
        )
        self.assertEqual(gateway.calls, [first, second])

    def test_exact_limit_stops_without_an_extra_model_or_tool_call(self) -> None:
        first = _call("call_1", "travel.search_places")
        second = _call("call_2", "travel.get_weather")
        unused = FinalAnswerDecision("不应被读取。")
        model = FakeExecutorModelClient(
            [ToolActionDecision(first), ToolActionDecision(second), unused]
        )
        gateway = FakeExecutorToolGateway(
            [
                _result(first, ToolCallStatus.SUCCEEDED),
                _result(second, ToolCallStatus.SUCCEEDED),
            ]
        )

        state = _invoke(model, gateway, limits=ExecutionLimits(max_steps=2))

        self.assertEqual(state["result"].status, ExecutorStatus.STOPPED)
        self.assertEqual(
            state["result"].stop_reason, ExecutorStopReason.LIMIT_REACHED
        )
        self.assertEqual(state["result"].step_count, 2)
        self.assertEqual(len(model.inputs), 2)
        self.assertEqual(gateway.calls, [first, second])

    def test_maximum_legal_limit_uses_explicit_stop_not_recursion_failure(self) -> None:
        calls = [
            _call(f"call_{index}", "travel.search_places")
            for index in range(1, 17)
        ]
        model = FakeExecutorModelClient(
            [ToolActionDecision(call) for call in calls]
        )
        gateway = FakeExecutorToolGateway(
            [_result(call, ToolCallStatus.SUCCEEDED) for call in calls]
        )

        state = _invoke(model, gateway, limits=ExecutionLimits(max_steps=16))

        self.assertEqual(
            state["result"].stop_reason, ExecutorStopReason.LIMIT_REACHED
        )
        self.assertEqual(state["result"].step_count, 16)
        self.assertEqual(len(gateway.calls), 16)

    def test_duplicate_call_id_fails_before_a_second_tool_execution(self) -> None:
        first = _call("call_1", "travel.search_places")
        duplicate = _call("call_1", "travel.get_weather")
        model = FakeExecutorModelClient(
            [ToolActionDecision(first), ToolActionDecision(duplicate)]
        )
        gateway = FakeExecutorToolGateway(
            [_result(first, ToolCallStatus.SUCCEEDED)]
        )

        state = _invoke(model, gateway)

        self.assertEqual(state["result"].status, ExecutorStatus.FAILED)
        self.assertEqual(
            state["result"].stop_reason,
            ExecutorStopReason.INVALID_MODEL_ACTION,
        )
        self.assertEqual(gateway.calls, [first])

    def test_denied_and_confirmation_results_stop_immediately(self) -> None:
        cases = (
            (
                ToolCallStatus.DENIED,
                ExecutorStopReason.SAFETY_DENIED,
                "tool_not_allowed",
            ),
            (
                ToolCallStatus.REQUIRES_CONFIRMATION,
                ExecutorStopReason.CONFIRMATION_REQUIRED,
                "confirmation_required",
            ),
        )
        for status, stop_reason, error_code in cases:
            with self.subTest(status=status):
                call = _call("call_1", "research.create_note")
                tool_result = _result(
                    call,
                    status,
                    error=ToolError(error_code, "Safe stop."),
                )
                state = _invoke(
                    FakeExecutorModelClient([ToolActionDecision(call)]),
                    FakeExecutorToolGateway([tool_result]),
                )

                self.assertEqual(state["result"].status, ExecutorStatus.STOPPED)
                self.assertEqual(state["result"].stop_reason, stop_reason)
                self.assertEqual(state["result"].error_code, error_code)

    def test_model_and_graph_dependency_failures_are_safe_results(self) -> None:
        call = _call("call_1", "travel.search_places")
        cases = (
            (
                _ExplodingModel(),
                FakeExecutorToolGateway([]),
                ExecutorStopReason.MODEL_FAILED,
                "executor_model_failed",
            ),
            (
                FakeExecutorModelClient([object()]),  # type: ignore[list-item]
                FakeExecutorToolGateway([]),
                ExecutorStopReason.INVALID_MODEL_ACTION,
                "executor_invalid_model_action",
            ),
            (
                _InvalidActionModel(),
                FakeExecutorToolGateway([]),
                ExecutorStopReason.INVALID_MODEL_ACTION,
                "executor_invalid_model_action",
            ),
            (
                FakeExecutorModelClient([ToolActionDecision(call)]),
                _ExplodingGateway(),
                ExecutorStopReason.EXECUTOR_INTERNAL_FAILED,
                "executor_tool_execution_failed",
            ),
        )
        for model, gateway, stop_reason, error_code in cases:
            with self.subTest(stop_reason=stop_reason):
                state = _invoke(model, gateway)
                result = state["result"]
                self.assertEqual(result.status, ExecutorStatus.FAILED)
                self.assertEqual(result.stop_reason, stop_reason)
                self.assertEqual(result.error_code, error_code)
                self.assertNotIn("private-provider-path", repr(result))

    def test_goal_not_achieved_is_only_valid_for_plan_step_invocation(self) -> None:
        model = FakeExecutorModelClient([GoalNotAchievedDecision("missing_scope")])
        state = _invoke(
            model,
            FakeExecutorToolGateway([]),
            plan_step=PlanStepExecutionInput(
                "plan_1", 1, "step_1", "goal", "objective", "outcome"
            ),
        )
        self.assertEqual(state["result"].status, ExecutorStatus.STOPPED)
        self.assertEqual(
            state["result"].stop_reason, ExecutorStopReason.GOAL_NOT_ACHIEVED
        )
        self.assertEqual(state["result"].error_code, "plan_step_goal_not_achieved")
        self.assertIsNotNone(model.inputs[0].plan_step)

        direct = _invoke(
            FakeExecutorModelClient([GoalNotAchievedDecision("invalid_direct")]),
            FakeExecutorToolGateway([]),
        )
        self.assertEqual(
            direct["result"].stop_reason, ExecutorStopReason.INVALID_MODEL_ACTION
        )


def _invoke(
    model,
    gateway,
    *,
    limits: ExecutionLimits | None = None,
    tool_catalog: tuple[dict[str, object], ...] = (),
    plan_step: PlanStepExecutionInput | None = None,
):
    graph = build_executor_graph()
    return invoke_executor_graph(
        graph,
        create_executor_state(_request(), tool_catalog=tool_catalog),
        ExecutorGraphContext(
            model_client=model,
            tool_executor=gateway,
            limits=limits or ExecutionLimits(),
            plan_step_input=plan_step,
        ),
    )


def _request() -> RuntimeRequest:
    return RuntimeRequest(
        user_input="执行请求",
        session_id="session_test",
        run_id="run_test",
    )


def _call(call_id: str, tool_name: str) -> ToolCall:
    return ToolCall(call_id=call_id, tool_name=tool_name)


def _result(
    call: ToolCall,
    status: ToolCallStatus,
    *,
    output: dict[str, object] | None = None,
    error: ToolError | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=status,
        output=output,
        error=error,
    )


class _ExplodingModel:
    def decide(self, model_input):
        raise RuntimeError("private-provider-path")


class _InvalidActionModel:
    def decide(self, model_input):
        raise InvalidExecutorModelActionError(
            "Safe invalid action.", code="executor_invalid_model_action"
        )


class _ExplodingGateway:
    def execute(self, call):
        raise RuntimeError("private-handler-path")


if __name__ == "__main__":
    unittest.main()
