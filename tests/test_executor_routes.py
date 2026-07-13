from __future__ import annotations

import unittest

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    ToolActionDecision,
    ToolObservation,
)
from app.executor.routes import route_after_decision, route_after_tool
from app.executor.state import create_executor_state
from app.runtime.models import RuntimeRequest
from app.tools.models import ToolCall, ToolCallStatus


class ExecutorRoutesTest(unittest.TestCase):
    def test_decision_route_distinguishes_tool_from_all_terminal_results(self) -> None:
        state = create_executor_state(_request())
        state["current_decision"] = ToolActionDecision(
            ToolCall(call_id="call_1", tool_name="travel.get_trip")
        )
        self.assertEqual(route_after_decision(state), "tool")

        for stop_reason, status in (
            (ExecutorStopReason.FINAL_ANSWER, ExecutorStatus.COMPLETED),
            (ExecutorStopReason.LIMIT_REACHED, ExecutorStatus.STOPPED),
            (ExecutorStopReason.MODEL_FAILED, ExecutorStatus.FAILED),
        ):
            with self.subTest(stop_reason=stop_reason):
                state["result"] = ExecutorResult(
                    run_id="run_test",
                    status=status,
                    stop_reason=stop_reason,
                    final_message="完成。" if status == ExecutorStatus.COMPLETED else None,
                    step_count=1,
                )
                self.assertEqual(route_after_decision(state), "end")

    def test_tool_route_continues_only_without_a_terminal_result(self) -> None:
        state = create_executor_state(_request())
        state["current_decision"] = FinalAnswerDecision("占位。")
        state["observations"] = [
            ToolObservation(
                step_index=1,
                call_id="call_1",
                tool_name="travel.get_trip",
                status=ToolCallStatus.SUCCEEDED,
            )
        ]
        self.assertEqual(route_after_tool(state), "continue")

        state["result"] = ExecutorResult(
            run_id="run_test",
            status=ExecutorStatus.STOPPED,
            stop_reason=ExecutorStopReason.SAFETY_DENIED,
            final_message=None,
            step_count=1,
        )
        self.assertEqual(route_after_tool(state), "end")


def _request() -> RuntimeRequest:
    return RuntimeRequest(user_input="执行请求", session_id="session_test")


if __name__ == "__main__":
    unittest.main()
