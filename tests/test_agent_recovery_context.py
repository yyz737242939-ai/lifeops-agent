import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent
from app.memory.memory_retriever import MemoryRetriever
from app.memory.memory_store import SemanticMemoryStore
from app.memory.profile_loader import ProfileLoader
from app.runtime.recovery_store import RunRecordStore
from app.runtime.run_state import ActionRecord, ActionStatus, RunState, StopReason


class AgentRecoveryContextTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_recovery_context_is_injected_without_entering_messages(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            recovery_store = RunRecordStore(Path(directory) / "runs.json")
            state = RunState(run_id="run-partial")
            recovery_store.start_run(state, user_input_summary="Continue work")
            recovery_store.record_action(
                state.run_id,
                ActionRecord(
                    call_id="call-1",
                    tool_name="list_tasks",
                    arguments={},
                    status=ActionStatus.COMPLETED,
                    result={"ok": True},
                ),
                tool_effect="read",
            )
            state.stop(StopReason.LLM_REQUEST_FAILED, partial=True)
            recovery_store.finish_run(state)
            agent = Agent(recovery_store=recovery_store)
            agent.profile_loader = ProfileLoader(Path(directory) / "missing_profile.md")
            agent.memory_retriever = MemoryRetriever(
                SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            )

            agent.chat("继续刚才")

        sent_input = create_response.call_args.kwargs["input"]
        recovery_messages = [
            message
            for message in sent_input
            if message["role"] == "system"
            and "Recent recovery context" in message["content"]
        ]
        self.assertEqual(len(recovery_messages), 1)
        self.assertIn("run-partial", recovery_messages[0]["content"])
        self.assertIn("Do not replay tools automatically", recovery_messages[0]["content"])
        self.assertEqual(agent.messages, [{"role": "user", "content": "继续刚才"}])

        parameters = llm_io.log_request.call_args.kwargs["parameters"]
        report = parameters["recovery_context"]
        self.assertTrue(report["recovery_context_injected"])
        self.assertEqual(report["recovery_context_run_ids"], ["run-partial"])

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_recovery_context_does_not_expose_write_tools(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            recovery_store = RunRecordStore(Path(directory) / "runs.json")
            state = RunState(run_id="run-failed")
            recovery_store.start_run(state, user_input_summary="Failed write")
            state.fail(StopReason.LLM_REQUEST_FAILED)
            recovery_store.finish_run(state)
            agent = Agent(recovery_store=recovery_store)
            agent.profile_loader = ProfileLoader(Path(directory) / "missing_profile.md")
            agent.memory_retriever = MemoryRetriever(
                SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            )

            agent.chat("恢复上次")

        tools = create_response.call_args.kwargs["tools"]
        tool_names = {tool["name"] for tool in tools}
        self.assertNotIn("add_task_note", tool_names)
        self.assertNotIn("create_task", tool_names)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_model_only_recovery_execution_claim_is_corrected(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="已恢复执行上次任务。",
        )
        with tempfile.TemporaryDirectory() as directory:
            recovery_store = RunRecordStore(Path(directory) / "runs.json")
            state = RunState(run_id="run-failed")
            recovery_store.start_run(state, user_input_summary="Failed run")
            state.fail(StopReason.LLM_REQUEST_FAILED)
            recovery_store.finish_run(state)
            agent = Agent(recovery_store=recovery_store)
            agent.profile_loader = ProfileLoader(Path(directory) / "missing_profile.md")
            agent.memory_retriever = MemoryRetriever(
                SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            )

            answer = agent.chat("恢复上次")

        self.assertIn("不能确认已经恢复执行", answer)
        self.assertEqual(
            agent.messages,
            [
                {"role": "user", "content": "恢复上次"},
                {"role": "assistant", "content": answer},
            ],
        )

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_recovery_status_answer_is_allowed_without_tool_replay(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="上次 run-failed 停在 llm_request_failed，没有成功动作。",
        )
        with tempfile.TemporaryDirectory() as directory:
            recovery_store = RunRecordStore(Path(directory) / "runs.json")
            state = RunState(run_id="run-failed")
            recovery_store.start_run(state, user_input_summary="Failed run")
            state.fail(StopReason.LLM_REQUEST_FAILED)
            recovery_store.finish_run(state)
            agent = Agent(recovery_store=recovery_store)
            agent.profile_loader = ProfileLoader(Path(directory) / "missing_profile.md")
            agent.memory_retriever = MemoryRetriever(
                SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            )

            answer = agent.chat("上次失败在哪")

        self.assertEqual(answer, "上次 run-failed 停在 llm_request_failed，没有成功动作。")
        self.assertEqual(len(agent.last_run_state.action_records), 0)


if __name__ == "__main__":
    unittest.main()
