from __future__ import annotations

import unittest

from app.executor.models import (
    ExecutionLimits,
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    PlanStepDependencyResult,
    PlanStepExecutionInput,
    ToolActionDecision,
    ToolObservation,
)
from app.tools.models import (
    ExecutionEvidence,
    ToolCall,
    ToolCallStatus,
    ToolError,
    ToolResult,
)


class ExecutorModelsTest(unittest.TestCase):
    def test_execution_limits_default_and_range_are_frozen(self) -> None:
        self.assertEqual(ExecutionLimits().max_steps, 8)
        self.assertEqual(ExecutionLimits(max_steps=1).max_steps, 1)
        self.assertEqual(ExecutionLimits(max_steps=16).max_steps, 16)

        for value in (0, 17, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ExecutionLimits(max_steps=value)  # type: ignore[arg-type]

    def test_model_decisions_are_mutually_exclusive_and_final_is_non_empty(self) -> None:
        call = ToolCall(
            call_id="call_1",
            tool_name="research.search_knowledge",
            arguments={"query": "ReAct"},
        )

        action = ToolActionDecision(call=call)
        final = FinalAnswerDecision(message="已完成。")

        self.assertEqual(action.call, call)
        self.assertFalse(hasattr(action, "message"))
        self.assertEqual(final.message, "已完成。")
        self.assertFalse(hasattr(final, "call"))
        with self.assertRaises(ValueError):
            FinalAnswerDecision(message="   ")
        with self.assertRaises(ValueError):
            ToolActionDecision(call="not-a-tool-call")  # type: ignore[arg-type]

    def test_tool_observation_is_an_explicit_safe_tool_result_projection(self) -> None:
        result = ToolResult(
            call_id="call_1",
            tool_name="research.search_knowledge",
            status=ToolCallStatus.FAILED,
            output={"matches": []},
            evidence=(
                ExecutionEvidence(
                    evidence_type="query",
                    summary="The safe query result was validated.",
                    reference="artifact://query-1",
                ),
            ),
            error=ToolError(
                code="provider_unavailable",
                message="The provider is unavailable.",
                retryable=True,
            ),
        )

        observation = ToolObservation.from_tool_result(step_index=2, result=result)

        self.assertEqual(observation.step_index, 2)
        self.assertEqual(observation.call_id, result.call_id)
        self.assertEqual(observation.tool_name, result.tool_name)
        self.assertEqual(observation.status, result.status)
        self.assertEqual(observation.output, result.output)
        self.assertEqual(observation.error, result.error)
        self.assertEqual(observation.evidence, result.evidence)
        self.assertFalse(hasattr(observation, "arguments"))
        self.assertFalse(hasattr(observation, "exception"))
        self.assertFalse(hasattr(observation, "provider_response"))

    def test_executor_result_enforces_status_stop_reason_and_final_message(self) -> None:
        completed = ExecutorResult(
            run_id="run_1",
            status=ExecutorStatus.COMPLETED,
            stop_reason=ExecutorStopReason.FINAL_ANSWER,
            final_message="已完成。",
            step_count=1,
        )
        self.assertEqual(completed.final_message, "已完成。")

        invalid_cases = (
            {
                "status": ExecutorStatus.COMPLETED,
                "stop_reason": ExecutorStopReason.FINAL_ANSWER,
                "final_message": None,
            },
            {
                "status": ExecutorStatus.STOPPED,
                "stop_reason": ExecutorStopReason.MODEL_FAILED,
                "final_message": None,
            },
            {
                "status": ExecutorStatus.FAILED,
                "stop_reason": ExecutorStopReason.LIMIT_REACHED,
                "final_message": None,
            },
        )
        for values in invalid_cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                ExecutorResult(run_id="run_1", step_count=1, **values)

    def test_plan_step_input_is_narrow_bounded_and_dependency_safe(self) -> None:
        dependency = PlanStepDependencyResult("read", "读取完成。")
        step_input = PlanStepExecutionInput(
            "plan_1",
            2,
            "write",
            "完成研究",
            "形成摘要",
            "得到可保存摘要",
            (dependency,),
            4,
        )
        self.assertEqual(step_input.dependency_results, (dependency,))
        self.assertEqual(GoalNotAchievedDecision("missing_scope").reason_code, "missing_scope")
        with self.assertRaises(ValueError):
            PlanStepExecutionInput(
                "plan_1", 1, "write", "goal", "objective", "outcome", (dependency, dependency)
            )
        with self.assertRaises(ValueError):
            PlanStepExecutionInput(
                "plan_1", 1, "write", "goal", "objective", "outcome", max_steps=17
            )


if __name__ == "__main__":
    unittest.main()
