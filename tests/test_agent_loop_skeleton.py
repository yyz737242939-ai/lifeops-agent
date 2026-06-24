import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent
from app.runtime.run_state import (
    ActionStatus,
    LoopLimits,
    RunStatus,
    StopReason,
)


def _function_call(call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        name="get_current_time",
        arguments="{}",
        call_id=call_id,
    )


class AgentLoopSkeletonTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_completed_run_tracks_rounds_actions_and_run_id(
        self,
        create_response,
        log_event,
        _log_raw_event,
    ) -> None:
        create_response.side_effect = [
            SimpleNamespace(output=[_function_call("call-1")], output_text=""),
            SimpleNamespace(output=[], output_text="done"),
        ]
        agent = Agent()

        answer = agent.chat("现在几点？")

        self.assertEqual(answer, "done")
        state = agent.last_run_state
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.stop_reason, StopReason.COMPLETED)
        self.assertEqual(state.chat_llm_round_count, 2)
        self.assertEqual(state.chat_tool_execution_attempt_count, 1)
        self.assertEqual(state.action_records[0].status, ActionStatus.COMPLETED)

        started_state = log_event.log_run_started.call_args.args[0]
        completed_state = log_event.log_run_completed.call_args.args[0]
        self.assertEqual(started_state.run_id, completed_state.run_id)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_llm_budget_stops_with_preserved_successful_action(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[_function_call("call-1")],
            output_text="",
        )
        agent = Agent(
            loop_limits=LoopLimits(
                max_llm_rounds=1,
                max_tool_calls_per_round=2,
                max_total_tool_calls=2,
            )
        )

        answer = agent.chat("现在几点？")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(state.status, RunStatus.PARTIAL)
        self.assertEqual(state.stop_reason, StopReason.LLM_BUDGET_EXHAUSTED)
        self.assertEqual(len(state.completed_action_records), 1)
        self.assertIn("已保留 1 个成功的工具结果", answer)
        self.assertEqual(create_response.call_count, 1)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_per_round_tool_budget_skips_remaining_calls(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[_function_call("call-1"), _function_call("call-2")],
            output_text="",
        )
        agent = Agent(
            loop_limits=LoopLimits(
                max_llm_rounds=2,
                max_tool_calls_per_round=1,
                max_total_tool_calls=3,
            )
        )

        answer = agent.chat("查询两次当前时间")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(state.status, RunStatus.PARTIAL)
        self.assertEqual(state.stop_reason, StopReason.TOOL_BUDGET_EXHAUSTED)
        self.assertEqual(state.chat_tool_execution_attempt_count, 1)
        self.assertEqual(
            [action.status for action in state.action_records],
            [ActionStatus.COMPLETED, ActionStatus.SKIPPED],
        )
        self.assertIn("工具调用数量已达到限制", answer)
        output_messages = [
            message
            for message in agent.messages
            if isinstance(message, dict)
            and message.get("type") == "function_call_output"
        ]
        self.assertEqual(
            {message["call_id"] for message in output_messages},
            {"call-1", "call-2"},
        )


if __name__ == "__main__":
    unittest.main()
