import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent
from app.runtime.recovery_store import RunRecordStore
from app.runtime.run_state import LoopLimits, RunState


def _call(call_id: str, name: str = "get_current_time", arguments: str = "{}"):
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=call_id,
    )


def _response(*calls: SimpleNamespace, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(output=list(calls), output_text=text)


class AgentRecoveryPersistenceTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_completed_run_is_persisted_with_action_summary(
        self,
        create_response,
        events,
        _llm_io,
    ) -> None:
        create_response.side_effect = [
            _response(_call("call-1")),
            _response(text="done"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            agent = Agent(recovery_store=RunRecordStore(path))

            answer = agent.chat("现在几点？")
            runs = RunRecordStore(path).list_recent_runs()

        self.assertEqual(answer, "done")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "completed")
        self.assertEqual(runs[0].stop_reason, "completed")
        self.assertEqual(runs[0].action_count, 1)
        self.assertEqual(runs[0].actions[0].tool_name, "get_current_time")
        self.assertEqual(runs[0].actions[0].effect, "read")
        events.log_run_completed.assert_called_once()

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_successful_action_before_budget_stop_is_persisted_as_partial(
        self,
        create_response,
        events,
        _llm_io,
    ) -> None:
        create_response.return_value = _response(_call("call-1"))
        limits = LoopLimits(
            max_llm_rounds=1,
            max_tool_calls_per_round=2,
            max_total_tool_calls=2,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            agent = Agent(loop_limits=limits, recovery_store=RunRecordStore(path))

            answer = agent.chat("现在几点？")
            run = RunRecordStore(path).list_recent_runs()[0]

        self.assertIn("已保留 1 个成功的工具结果", answer)
        self.assertEqual(run.status, "partial")
        self.assertEqual(run.stop_reason, "llm_budget_exhausted")
        self.assertEqual(run.last_successful_action.tool_name, "get_current_time")
        events.log_run_stopped.assert_called_once()

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_llm_failure_without_successful_action_is_persisted_as_failed(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.side_effect = ValueError("bad request")
        limits = LoopLimits(max_llm_retries=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            agent = Agent(loop_limits=limits, recovery_store=RunRecordStore(path))

            answer = agent.chat("你好")
            run = RunRecordStore(path).list_recent_runs()[0]

        self.assertIn("模型请求失败", answer)
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.stop_reason, "llm_request_failed")
        self.assertEqual(run.action_count, 0)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_llm_failure_after_successful_action_is_persisted_as_partial(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.side_effect = [
            _response(_call("call-1")),
            ValueError("bad request"),
        ]
        limits = LoopLimits(max_llm_retries=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            agent = Agent(loop_limits=limits, recovery_store=RunRecordStore(path))

            answer = agent.chat("现在几点？")
            run = RunRecordStore(path).list_recent_runs()[0]

        self.assertIn("已保留 1 个成功的工具结果", answer)
        self.assertEqual(run.status, "partial")
        self.assertEqual(run.stop_reason, "llm_request_failed")
        self.assertEqual(run.last_successful_action.tool_name, "get_current_time")

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_new_chat_marks_previous_running_record_interrupted(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = _response(text="done")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            stale_store = RunRecordStore(path)
            stale_store.start_run(
                RunState(run_id="run-stale"),
                user_input_summary="Previous run",
            )
            agent = Agent(recovery_store=RunRecordStore(path))

            agent.chat("你好")
            runs = {run.run_id: run for run in RunRecordStore(path).list_recent_runs()}

        self.assertEqual(runs["run-stale"].status, "interrupted")
        self.assertEqual(runs["run-stale"].stop_reason, "process_interrupted")


if __name__ == "__main__":
    unittest.main()
