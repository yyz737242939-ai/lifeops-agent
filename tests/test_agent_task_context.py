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


class AgentTaskContextTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_task_context_is_injected_without_entering_messages(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task State v1",
                goal="Build request-local task context",
                steps=["Implement task_context.py"],
            )
            agent = Agent()
            agent.profile_loader = ProfileLoader(Path(directory) / "missing_profile.md")
            agent.memory_retriever = MemoryRetriever(
                SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            )
            agent.task_context_builder = TaskContextBuilder(store)

            agent.chat("继续上次任务")

        sent_input = create_response.call_args.kwargs["input"]
        task_messages = [
            message
            for message in sent_input
            if message["role"] == "system"
            and "Current task context" in message["content"]
        ]
        self.assertEqual(len(task_messages), 1)
        self.assertIn(task.id, task_messages[0]["content"])
        self.assertIn("Implement task_context.py", task_messages[0]["content"])
        self.assertEqual(
            agent.messages,
            [{"role": "user", "content": "继续上次任务"}],
        )

        request_parameters = llm_io.log_request.call_args.kwargs["parameters"]
        task_report = request_parameters["task_context"]
        self.assertTrue(task_report["task_context_injected"])
        self.assertEqual(task_report["task_context_task_ids"], [task.id])
        self.assertEqual(task_report["task_context_reason"], "latest_active_task")

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_non_task_request_does_not_inject_task_context(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            store.create_task(title="Task State v1", goal="Build task context")
            agent = Agent()
            agent.profile_loader = ProfileLoader(Path(directory) / "missing_profile.md")
            agent.memory_retriever = MemoryRetriever(
                SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            )
            agent.task_context_builder = TaskContextBuilder(store)

            agent.chat("今天怎么安排学习？")

        sent_input = create_response.call_args.kwargs["input"]
        self.assertEqual(sent_input, [{"role": "user", "content": "今天怎么安排学习？"}])
        request_parameters = llm_io.log_request.call_args.kwargs["parameters"]
        self.assertFalse(request_parameters["task_context"]["task_context_injected"])


if __name__ == "__main__":
    unittest.main()
