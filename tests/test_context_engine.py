import unittest
from types import SimpleNamespace

from app.runtime.context_budget import ContextBudgetConfig
from app.runtime.context_engine import ContextEngine


class ContextEngineTests(unittest.TestCase):
    def test_pass_through_assembly_keeps_input_messages_unchanged(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

        assembly = ContextEngine().assemble(
            messages,
            instructions="system",
            tools=[{"name": "example_tool"}],
        )

        self.assertEqual(assembly.input_messages, messages)
        self.assertIsNot(assembly.input_messages, messages)
        self.assertEqual(assembly.report["mode"], "pass_through_with_units")
        self.assertEqual(assembly.report["message_count"], 2)
        self.assertEqual(assembly.report["unit_count"], 2)
        self.assertEqual(
            assembly.report["unit_breakdown"],
            {"user": 1, "assistant": 1},
        )
        self.assertGreater(assembly.report["estimated_input_tokens"], 0)
        self.assertEqual(assembly.report["tool_schema_count"], 1)

    def test_function_call_and_observation_are_one_tool_unit(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            name="list_todos",
            arguments="{}",
            call_id="call-1",
        )
        observation = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"ok":true,"items":[]}',
        }
        messages = [
            {"role": "user", "content": "list todos"},
            call,
            observation,
            {"role": "assistant", "content": "none"},
        ]

        assembly = ContextEngine().assemble(messages)

        self.assertEqual(assembly.input_messages, messages)
        self.assertEqual(assembly.report["unit_breakdown"]["tool"], 1)
        tool_units = [
            unit
            for unit in assembly.report["units"]
            if unit["kind"] == "tool"
        ]
        self.assertEqual(len(tool_units), 1)
        self.assertEqual(tool_units[0]["message_count"], 2)
        self.assertFalse(tool_units[0]["protected"])
        self.assertEqual(tool_units[0]["metadata"]["call_id"], "call-1")
        self.assertTrue(tool_units[0]["metadata"]["paired_observation"])

    def test_unpaired_tool_messages_are_protected(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            name="list_todos",
            arguments="{}",
            call_id="call-1",
        )

        assembly = ContextEngine().assemble([call])

        self.assertEqual(assembly.report["protected_unit_count"], 1)
        tool_unit = assembly.report["units"][0]
        self.assertEqual(tool_unit["kind"], "tool")
        self.assertTrue(tool_unit["protected"])
        self.assertFalse(tool_unit["metadata"]["paired_observation"])

    def test_sliding_window_limits_assembled_input_but_keeps_full_store(self) -> None:
        messages = [
            {"role": "user", "content": f"old user message {index} " + ("x" * 80)}
            for index in range(20)
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=120)
        )

        assembly = engine.assemble(messages)

        self.assertLess(len(assembly.input_messages), len(messages))
        self.assertEqual(engine.store.full_messages, messages)
        self.assertEqual(
            assembly.input_messages[0]["content"],
            ContextEngine.COMPACTED_HISTORY_NOTE,
        )
        self.assertEqual(assembly.report["mode"], "windowed_with_placeholder_summary")
        self.assertGreater(assembly.report["evicted_unit_count"], 0)
        self.assertEqual(
            assembly.report["assembled_message_count"],
            len(assembly.input_messages),
        )

    def test_sliding_window_does_not_split_tool_call_from_observation(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            name="list_todos",
            arguments="{}",
            call_id="call-1",
        )
        observation = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"ok":true,"items":[{"id":"todo-1"}]}',
        }
        messages = [
            {"role": "user", "content": "old " + ("x" * 200)},
            {"role": "assistant", "content": "old answer " + ("x" * 200)},
            call,
            observation,
            {"role": "assistant", "content": "todo-1"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=140)
        )

        assembly = engine.assemble(messages)

        self.assertIn(call, assembly.input_messages)
        self.assertIn(observation, assembly.input_messages)
        self.assertLess(len(assembly.input_messages), len(messages) + 1)

    def test_protected_old_units_are_kept_outside_recent_window(self) -> None:
        protected_call = SimpleNamespace(
            type="function_call",
            name="list_todos",
            arguments="{}",
            call_id="call-protected",
        )
        messages = [protected_call] + [
            {"role": "user", "content": f"recent {index} " + ("x" * 120)}
            for index in range(10)
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=80)
        )

        assembly = engine.assemble(messages)

        self.assertIn(protected_call, assembly.input_messages)
        self.assertGreater(assembly.report["protected_unit_count"], 0)
        self.assertGreater(assembly.report["evicted_unit_count"], 0)


if __name__ == "__main__":
    unittest.main()
