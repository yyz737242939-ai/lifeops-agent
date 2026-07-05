import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.agents.agent import Agent
from app.memory.memory_retriever import MemoryRetriever
from app.memory.memory_store import SemanticMemoryStore
from app.memory.profile_loader import ProfileLoader
from app.tasks.task_context import TaskContextBuilder
from app.tasks.task_store import TaskStore


def _function_call(name: str, arguments: dict[str, object], call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
        call_id=call_id,
    )


def _isolated_agent(directory: str, store: TaskStore) -> Agent:
    agent = Agent()
    root = Path(directory)
    agent.profile_loader = ProfileLoader(root / "missing_profile.md")
    agent.memory_retriever = MemoryRetriever(
        SemanticMemoryStore(root / "semantic_memories.json")
    )
    agent.task_context_builder = TaskContextBuilder(store)
    return agent


class AgentTaskStateTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_agent_creates_task_from_natural_language(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.side_effect = [
            SimpleNamespace(
                output=[
                    _function_call(
                        "create_task",
                        {
                            "title": "Task State v1",
                            "goal": "Complete the Task State v1 runtime loop",
                            "steps": ["Register tools", "Verify agent loop"],
                            "tags": ["runtime"],
                        },
                        "call_task_create",
                    )
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[],
                output_text="已创建任务：Task State v1。",
            ),
        ]

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            agent = _isolated_agent(directory, store)
            with patch("app.tools.tool.task_store", store):
                answer = agent.chat("帮我创建任务：完成 Task State v1。")
            stored = store.list_tasks(tag="runtime")

        self.assertIn("已创建任务", answer)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].title, "Task State v1")
        self.assertEqual([step.title for step in stored[0].steps], ["Register tools", "Verify agent loop"])
        state = agent.last_run_state
        assert state is not None
        self.assertEqual(
            [action.tool_name for action in state.completed_action_records],
            ["create_task"],
        )
        first_tools = {schema["name"] for schema in create_response.call_args_list[0].kwargs["tools"]}
        self.assertIn("create_task", first_tools)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_agent_adds_step_and_blocker_to_existing_task(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task State v1",
                goal="Complete the Task State v1 runtime loop",
                steps=["Register tools"],
            )
            create_response.side_effect = [
                SimpleNamespace(
                    output=[
                        _function_call(
                            "add_task_step",
                            {
                                "task_id": task.id,
                                "title": "Write Agent loop tests",
                            },
                            "call_add_step",
                        ),
                        _function_call(
                            "add_task_blocker",
                            {
                                "task_id": task.id,
                                "reason": "Need authorization boundary decision",
                            },
                            "call_add_blocker",
                        ),
                    ],
                    output_text="",
                ),
                SimpleNamespace(
                    output=[],
                    output_text="已更新任务，并记录 blocker。",
                ),
            ]
            agent = _isolated_agent(directory, store)

            with patch("app.tools.tool.task_store", store):
                answer = agent.chat(
                    "给这个任务添加一个步骤：Write Agent loop tests。"
                    "这个任务卡住了，原因是 Need authorization boundary decision。"
                )
            updated = store.get_task(task.id)

        self.assertIn("已更新任务", answer)
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.status, "blocked")
        self.assertEqual(updated.steps[-1].title, "Write Agent loop tests")
        self.assertEqual(
            updated.open_blockers[0].reason,
            "Need authorization boundary decision",
        )
        state = agent.last_run_state
        assert state is not None
        self.assertEqual(
            [action.tool_name for action in state.completed_action_records],
            ["add_task_step", "add_task_blocker"],
        )

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_resume_task_uses_context_without_authorizing_writes(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="当前任务是 Task State v1，下一步是 Write tests。",
        )

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task State v1",
                goal="Complete Task State",
                steps=["Write tests"],
            )
            agent = _isolated_agent(directory, store)

            answer = agent.chat("继续上次任务")

        self.assertIn("Write tests", answer)
        sent_tools = {schema["name"] for schema in create_response.call_args.kwargs["tools"]}
        self.assertIn("list_tasks", sent_tools)
        self.assertIn("get_task", sent_tools)
        self.assertNotIn("update_task_status", sent_tools)
        self.assertNotIn("add_task_step", sent_tools)
        sent_input = create_response.call_args.kwargs["input"]
        self.assertTrue(
            any(
                message["role"] == "system"
                and "Current task context" in message["content"]
                and task.id in message["content"]
                for message in sent_input
            )
        )
        task_report = llm_io.log_request.call_args.kwargs["parameters"]["task_context"]
        self.assertEqual(task_report["task_context_task_ids"], [task.id])

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    @patch("app.tools.tool.todo_store.delete_todo")
    def test_resuming_task_does_not_authorize_dangerous_write(
        self,
        delete_todo,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        denied_call = _function_call("delete_todo", {"todo_id": 1}, "call_delete")
        create_response.side_effect = [
            SimpleNamespace(output=[denied_call], output_text=""),
            SimpleNamespace(output=[], output_text="不会执行删除。"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            store.create_task(
                title="Cleanup task",
                goal="Review whether old todos should be deleted",
                steps=["Confirm delete scope"],
            )
            agent = _isolated_agent(directory, store)

            answer = agent.chat("继续上次任务")

        self.assertIn("不会执行删除", answer)
        delete_todo.assert_not_called()
        state = agent.last_run_state
        assert state is not None
        self.assertEqual(state.failed_action_records[0].tool_name, "delete_todo")
        self.assertEqual(state.failed_action_records[0].error["code"], "tool_not_allowed")

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_model_cannot_claim_task_write_without_successful_action(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="已创建任务：Task State v1。",
        )
        agent = Agent()

        answer = agent.chat("我想完成 Task State v1。")

        self.assertIn("没有收到任何成功的写入结果", answer)


if __name__ == "__main__":
    unittest.main()
