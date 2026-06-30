import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.agents.agent import Agent
from app.domains.todo_store import Todo
from app.runtime.run_state import LoopLimits, RunStatus, StopReason
from app.tools.tool import TOOLS


def _call(name: str, arguments: str, call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=call_id,
    )


def _response(*calls: SimpleNamespace, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(output=list(calls), output_text=text)


class FakeLLMTimeout(Exception):
    pass


class AgentLoopReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = LoopLimits(
            max_llm_rounds=5,
            max_tool_calls_per_round=6,
            max_total_tool_calls=12,
            max_tool_retries=2,
            max_llm_retries=2,
            max_same_call_attempts=2,
            max_identical_observations=2,
            retry_backoff_seconds=0,
        )

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_llm_timeout_is_retried_explicitly(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        create_response.side_effect = [FakeLLMTimeout("slow"), _response(text="done")]
        agent = Agent(loop_limits=self.limits)

        answer = agent.chat("你好")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(answer, "done")
        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.chat_llm_round_count, 1)
        self.assertEqual(state.chat_llm_request_count, 2)
        self.assertEqual(state.chat_retry_counts_by_operation["llm:1"], 1)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_llm_failure_after_tool_success_returns_partial_result(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        create_response.side_effect = [
            _response(_call("get_current_time", "{}", "call-1")),
            ValueError("bad request"),
        ]
        agent = Agent(loop_limits=self.limits)

        answer = agent.chat("现在几点？")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(state.status, RunStatus.PARTIAL)
        self.assertEqual(state.stop_reason, StopReason.LLM_REQUEST_FAILED)
        self.assertEqual(len(state.completed_action_records), 1)
        self.assertIn("get_current_time", answer)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_read_tool_transient_error_is_retried(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        original = TOOLS["get_current_time"]
        function = Mock(
            side_effect=[
                OSError("temporary"),
                {"ok": True, "action": "get_current_time", "current_time": "now"},
            ]
        )
        create_response.side_effect = [
            _response(_call("get_current_time", "{}", "call-1")),
            _response(text="done"),
        ]
        agent = Agent(loop_limits=self.limits)

        with patch.dict(TOOLS, {"get_current_time": replace(original, function=function)}):
            answer = agent.chat("现在几点？")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(answer, "done")
        self.assertEqual(function.call_count, 2)
        self.assertEqual(
            state.action_records[0].tool_execution_attempt_count,
            2,
        )
        self.assertEqual(state.chat_tool_execution_attempt_count, 2)
        self.assertEqual(
            state.chat_retry_counts_by_operation["tool:call-1"],
            1,
        )

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_non_idempotent_write_error_is_not_retried(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        original = TOOLS["add_todo"]
        function = Mock(side_effect=OSError("result unknown"))
        create_response.side_effect = [
            _response(_call("add_todo", '{"title":"test"}', "call-1")),
            _response(text="could not add"),
        ]
        agent = Agent(loop_limits=self.limits)

        with (
            patch.dict(TOOLS, {"add_todo": replace(original, function=function)}),
            patch("app.tools.tool.get_idempotent_result", return_value=None),
        ):
            answer = agent.chat("添加待办 test")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(answer, "could not add")
        self.assertEqual(function.call_count, 1)
        self.assertEqual(
            state.action_records[0].tool_execution_attempt_count,
            1,
        )
        self.assertNotIn("tool:call-1", state.chat_retry_counts_by_operation)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    @patch("app.tools.tool.save_idempotent_result")
    @patch("app.tools.tool.get_idempotent_result", return_value=None)
    @patch("app.tools.tool.todo_store.add_todo")
    def test_repeated_non_idempotent_write_is_skipped(
        self,
        add_todo,
        _get_idempotent_result,
        _save_idempotent_result,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        add_todo.return_value = Todo(id=1, title="学习 Agent Loop")
        repeated = '{"title":"学习 Agent Loop"}'
        create_response.side_effect = [
            _response(_call("add_todo", repeated, "call-1")),
            _response(_call("add_todo", repeated, "call-2")),
        ]
        agent = Agent(loop_limits=self.limits)

        answer = agent.chat("添加待办：学习 Agent Loop")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(add_todo.call_count, 1)
        self.assertEqual(state.stop_reason, StopReason.REPEATED_CALL)
        self.assertEqual(state.status, RunStatus.PARTIAL)
        self.assertIn("重复工具调用", answer)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_identical_read_observation_stops_no_progress(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        repeated = '{"ref_id":"missing"}'
        create_response.side_effect = [
            _response(_call("read_context_ref", repeated, "call-1")),
            _response(_call("read_context_ref", repeated, "call-2")),
        ]
        agent = Agent(loop_limits=self.limits)

        answer = agent.chat("展开引用 missing")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(state.stop_reason, StopReason.NO_PROGRESS)
        self.assertEqual(len(state.failed_action_records), 2)
        self.assertIn("没有产生新进展", answer)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_cooperative_cancel_skips_returned_tool_call(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        agent = Agent(loop_limits=self.limits)

        def cancel_then_respond(**_kwargs):
            self.assertTrue(agent.cancel_current_run())
            return _response(_call("get_current_time", "{}", "call-1"))

        create_response.side_effect = cancel_then_respond

        answer = agent.chat("现在几点？")

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(state.stop_reason, StopReason.CANCELLED)
        self.assertEqual(state.action_records[0].status.value, "skipped")
        self.assertIn("已取消", answer)


if __name__ == "__main__":
    unittest.main()
