from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.agents.agent import Agent
from app.memory.memory_retriever import MemoryRetriever
from app.memory.memory_store import SemanticMemoryStore
from app.memory.profile_loader import ProfileLoader


class AgentMemoryContextTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_profile_context_is_injected_without_entering_messages(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.md"
            profile_path.write_text("用户偏好中文解释。", encoding="utf-8")
            agent = Agent()
            agent.profile_loader = ProfileLoader(profile_path)

            agent.chat("今天怎么安排学习？")

        sent_input = create_response.call_args.kwargs["input"]
        self.assertEqual(sent_input[0]["role"], "system")
        self.assertIn("Long-term profile", sent_input[0]["content"])
        self.assertIn("用户偏好中文解释。", sent_input[0]["content"])
        self.assertEqual(
            agent.messages,
            [{"role": "user", "content": "今天怎么安排学习？"}],
        )

        request_parameters = llm_io.log_request.call_args.kwargs["parameters"]
        self.assertTrue(request_parameters["memory"]["profile_loaded"])
        self.assertTrue(request_parameters["memory"]["profile_injected"])

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_missing_profile_does_not_add_context_message(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent()
            agent.profile_loader = ProfileLoader(Path(directory) / "missing.md")

            agent.chat("hello")

        sent_input = create_response.call_args.kwargs["input"]
        self.assertEqual(sent_input, [{"role": "user", "content": "hello"}])
        request_parameters = llm_io.log_request.call_args.kwargs["parameters"]
        self.assertFalse(request_parameters["memory"]["profile_loaded"])
        self.assertFalse(request_parameters["memory"]["profile_injected"])

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_relevant_semantic_memory_is_injected_without_entering_messages(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            memory = store.save_memory(
                memory_type="preference",
                content="用户喜欢早上学习。",
                tags=["learning"],
            )
            agent = Agent()
            agent.profile_loader = ProfileLoader(Path(directory) / "missing.md")
            agent.memory_retriever = MemoryRetriever(store)

            agent.chat("今天怎么安排学习？")

        sent_input = create_response.call_args.kwargs["input"]
        self.assertEqual(sent_input[0]["role"], "system")
        self.assertIn("Relevant saved memories", sent_input[0]["content"])
        self.assertIn(memory.id, sent_input[0]["content"])
        self.assertIn("用户喜欢早上学习。", sent_input[0]["content"])
        self.assertEqual(
            agent.messages,
            [{"role": "user", "content": "今天怎么安排学习？"}],
        )

        request_parameters = llm_io.log_request.call_args.kwargs["parameters"]
        self.assertEqual(request_parameters["memory"]["semantic_memory_ids"], [memory.id])
        self.assertTrue(request_parameters["memory"]["semantic_memory_injected"])

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_deleted_semantic_memory_is_not_injected(
        self,
        create_response,
        _events,
        llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            memory = store.save_memory(
                memory_type="preference",
                content="用户喜欢早上学习。",
            )
            store.delete_memory(memory.id)
            agent = Agent()
            agent.profile_loader = ProfileLoader(Path(directory) / "missing.md")
            agent.memory_retriever = MemoryRetriever(store)

            agent.chat("今天怎么安排学习？")

        sent_input = create_response.call_args.kwargs["input"]
        self.assertEqual(sent_input, [{"role": "user", "content": "今天怎么安排学习？"}])
        request_parameters = llm_io.log_request.call_args.kwargs["parameters"]
        self.assertEqual(request_parameters["memory"]["semantic_memory_ids"], [])
        self.assertFalse(request_parameters["memory"]["semantic_memory_injected"])


if __name__ == "__main__":
    unittest.main()
