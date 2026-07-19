from __future__ import annotations

import unittest

from app.executor.models import (
    ExecutionLimits,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    PlanStepDependencyResult,
    PlanStepExecutionInput,
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
    FakeExecutorMemoryProvider,
    FakeExecutorModelClient,
    RecordingExecutorFeedbackSink,
    RecordingExecutorRecoveryHook,
)
from app.executor.models import ToolActionDecision


class ExecutorPlanStepTest(unittest.TestCase):
    def test_execute_step_passes_only_current_step_and_uses_smaller_limit(self) -> None:
        model = FakeExecutorModelClient(
            [FinalAnswerDecision("当前 Step 已完成。")]
        )
        executor = ReactExecutor(model, limits=ExecutionLimits(max_steps=8))
        step_input = _step_input(max_steps=3)

        result = executor.execute_step(
            _request(),
            step_input,
            (),
            AllowedToolSet(),
            ToolRuntime.from_registry(ToolRegistry()),
        )

        self.assertEqual(result.status, ExecutorStatus.COMPLETED)
        self.assertIs(model.inputs[0].plan_step, step_input)
        self.assertFalse(hasattr(step_input, "future_steps"))

    def test_plan_step_identity_reaches_input_and_observer_hooks(self) -> None:
        step_input = _step_input()
        context = FakeExecutorContextProvider(())
        memory = FakeExecutorMemoryProvider(())
        feedback = RecordingExecutorFeedbackSink()
        recovery = RecordingExecutorRecoveryHook()
        executor = ReactExecutor(
            FakeExecutorModelClient([FinalAnswerDecision("完成。")]),
            context_provider=context,
            memory_provider=memory,
            feedback_sink=feedback,
            recovery_hook=recovery,
        )

        executor.execute_step(
            _request(),
            step_input,
            (),
            AllowedToolSet(),
            ToolRuntime.from_registry(ToolRegistry()),
        )

        self.assertEqual(context.plan_steps, [step_input])
        self.assertEqual(memory.plan_steps, [step_input])
        self.assertEqual(feedback.plan_steps, [step_input])
        self.assertEqual(feedback.run_ids, ["run_1"])
        self.assertTrue(feedback.executor_invocation_ids[0])
        self.assertEqual(feedback.tool_effects, [None])
        self.assertEqual(recovery.plan_steps, [step_input])

    def test_plan_step_limit_is_capped_by_executor_composition(self) -> None:
        calls = (
            ToolCall("call_1", "test.read"),
            ToolCall("call_2", "test.read"),
        )
        model = FakeExecutorModelClient(
            [
                ToolActionDecision(calls[0]),
                ToolActionDecision(calls[1]),
                FinalAnswerDecision("unused"),
            ]
        )
        executor = ReactExecutor(model, limits=ExecutionLimits(max_steps=2))
        runtime = _runtime()
        result = executor.execute_step(
            _request(),
            _step_input(max_steps=6),
            (),
            AllowedToolSet(("test.read",)),
            runtime,
        )
        self.assertEqual(result.status, ExecutorStatus.STOPPED)
        self.assertEqual(result.stop_reason, ExecutorStopReason.LIMIT_REACHED)
        self.assertEqual(len(model.inputs), 2)

    def test_fake_goal_not_achieved_maps_to_structured_step_result(self) -> None:
        model = FakeExecutorModelClient([GoalNotAchievedDecision("missing_scope")])
        result = ReactExecutor(model).execute_step(
            _request(),
            _step_input(),
            (),
            AllowedToolSet(),
            ToolRuntime.from_registry(ToolRegistry()),
        )
        self.assertEqual(result.status, ExecutorStatus.STOPPED)
        self.assertEqual(result.stop_reason, ExecutorStopReason.GOAL_NOT_ACHIEVED)
        self.assertEqual(result.error_code, "plan_step_goal_not_achieved")

    def test_direct_execute_remains_compatible_and_has_no_plan_step(self) -> None:
        model = FakeExecutorModelClient([FinalAnswerDecision("直接完成。")])
        result = ReactExecutor(model).execute(
            _request(),
            (),
            AllowedToolSet(),
            ToolRuntime.from_registry(ToolRegistry()),
        )
        self.assertEqual(result.status, ExecutorStatus.COMPLETED)
        self.assertIsNone(model.inputs[0].plan_step)


def _request() -> RuntimeRequest:
    return RuntimeRequest("执行请求", "session_1", run_id="run_1")


def _step_input(*, max_steps: int = 3) -> PlanStepExecutionInput:
    return PlanStepExecutionInput(
        "plan_1",
        1,
        "write",
        "完成研究",
        "形成摘要",
        "得到摘要",
        (PlanStepDependencyResult("read", "读取完成。"),),
        max_steps,
    )


def _runtime() -> ToolRuntime:
    definition = ToolDefinition(
        "test.read",
        "Read test data.",
        {"type": "object", "properties": {}},
        {"type": "object", "properties": {}},
        ToolEffect.READ,
        ToolRisk.LOW,
    )

    def handler(call: ToolCall) -> ToolResult:
        return ToolResult(call.call_id, call.tool_name, ToolCallStatus.SUCCEEDED, {})

    return ToolRuntime.from_registry(ToolRegistry(((definition, handler),)))


if __name__ == "__main__":
    unittest.main()
