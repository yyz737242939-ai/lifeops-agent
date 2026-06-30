import unittest
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
