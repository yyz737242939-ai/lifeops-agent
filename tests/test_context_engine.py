import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.context.context_budget import ContextBudgetConfig
from app.context.context_engine import ContextEngine


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
        self.assertEqual(
            assembly.report["inspection"]["decisions"][0]["status"],
            "within_recent_window",
        )
        self.assertEqual(
            assembly.report["inspection"]["composition"]["recent_units"],
            2,
        )

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
        diagnostics = assembly.report["inspection"]["diagnostics"]
        self.assertIn(
            "history_compacted_without_summary",
            [diagnostic["code"] for diagnostic in diagnostics],
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

    def test_after_turn_updates_summary_for_evicted_units(self) -> None:
        messages = [
            {"role": "user", "content": f"old goal {index} " + ("x" * 80)}
            for index in range(12)
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=120)
        )

        report = engine.after_turn(messages)
        assembly = engine.assemble(messages)

        self.assertTrue(report["compacted"])
        self.assertEqual(report["reason"], "rolling_summary_updated")
        self.assertIsNotNone(engine.store.summary)
        self.assertIsNotNone(engine.store.summary_message)
        self.assertEqual(assembly.report["mode"], "windowed_with_summary")
        self.assertTrue(assembly.report["summary_inserted"])
        self.assertFalse(assembly.report["placeholder_summary_inserted"])
        self.assertEqual(assembly.input_messages[0]["role"], "system")
        self.assertIn("[Context summary]", assembly.input_messages[0]["content"])

    def test_rolling_summary_replaces_state_without_duplicate_sources(self) -> None:
        messages = [
            {"role": "user", "content": f"old goal {index} " + ("x" * 80)}
            for index in range(12)
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=120)
        )

        first = engine.after_turn(messages)
        first_sources = list(engine.store.summary["source_unit_ids"])
        second = engine.after_turn(messages)
        second_sources = list(engine.store.summary["source_unit_ids"])

        self.assertTrue(first["compacted"])
        self.assertTrue(second["compacted"])
        self.assertEqual(first_sources, second_sources)
        self.assertEqual(len(second_sources), len(set(second_sources)))

    def test_summary_does_not_trust_assistant_success_claim(self) -> None:
        messages = [
            {"role": "user", "content": "add a todo " + ("x" * 120)},
            {"role": "assistant", "content": "Saved it successfully." + ("x" * 120)},
            {"role": "user", "content": "new question"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=80)
        )

        engine.after_turn(messages)

        self.assertEqual(engine.store.summary["successful_actions"], [])

    def test_summary_records_runtime_tool_success(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            name="add_todo",
            arguments='{"title":"pay rent"}',
            call_id="call-1",
        )
        observation = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": json.dumps(
                {"ok": True, "action": "add_todo", "id": "todo-1"},
                ensure_ascii=False,
            ),
        }
        messages = [
            {"role": "user", "content": "please add a todo " + ("x" * 120)},
            call,
            observation,
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "new question"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=80)
        )

        engine.after_turn(messages)

        self.assertIn(
            {
                "unit_id": "u_0002",
                "tool_name": "add_todo",
                "call_id": "call-1",
                "action": "add_todo",
            },
            engine.store.summary["successful_actions"],
        )
        self.assertIn(
            {"unit_id": "u_0002", "type": "id", "value": "todo-1"},
            engine.store.summary["important_entities"],
        )

    def test_retrieves_evicted_tool_unit_by_todo_id(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            name="list_todos",
            arguments="{}",
            call_id="call-1",
        )
        observation = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": json.dumps(
                {
                    "ok": True,
                    "action": "list_todos",
                    "todos": [
                        {
                            "id": 42,
                            "title": "pay rent",
                            "status": "todo",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        }
        messages = [
            {"role": "user", "content": "old todo lookup " + ("x" * 120)},
            call,
            observation,
            {"role": "assistant", "content": "I found task 42." + ("x" * 120)},
            {"role": "user", "content": "complete todo id 42"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=40)
        )

        assembly = engine.assemble(messages)

        self.assertIn(call, assembly.input_messages)
        self.assertIn(observation, assembly.input_messages)
        self.assertEqual(assembly.report["retrieved_unit_count"], 1)
        self.assertEqual(
            assembly.report["retrieved_units"][0]["reason"],
            "matched_entity_id",
        )
        self.assertIn(
            "entity_id",
            assembly.report["retrieved_units"][0]["matched_fields"],
        )

    def test_general_summary_does_not_retrieve_evicted_ref_unit(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            name="list_todos",
            arguments="{}",
            call_id="call-1",
        )
        observation = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": json.dumps(
                {
                    "ok": True,
                    "compacted": True,
                    "compaction_strategy": "summary_reference",
                    "summary": {"count": 10},
                    "ref_id": "ctx_test",
                },
                ensure_ascii=False,
            ),
        }
        messages = [
            {"role": "user", "content": "old todo lookup " + ("x" * 120)},
            call,
            observation,
            {"role": "assistant", "content": "I found a list." + ("x" * 120)},
            {"role": "user", "content": "summarize the previous todo list"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=40)
        )

        with patch("app.context.context_index.read_context_ref") as read_ref:
            assembly = engine.assemble(messages)

        read_ref.assert_not_called()
        self.assertNotIn(call, assembly.input_messages)
        self.assertEqual(assembly.report["retrieved_unit_count"], 0)
        self.assertEqual(assembly.report["retrieved_ref_count"], 0)

    def test_exact_followup_loads_retrieved_ref(self) -> None:
        call = SimpleNamespace(
            type="function_call",
            name="list_todos",
            arguments="{}",
            call_id="call-1",
        )
        observation = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": json.dumps(
                {
                    "ok": True,
                    "compacted": True,
                    "compaction_strategy": "summary_reference",
                    "summary": {"count": 10},
                    "ref_id": "ctx_test",
                },
                ensure_ascii=False,
            ),
        }
        messages = [
            {"role": "user", "content": "old todo lookup " + ("x" * 120)},
            call,
            observation,
            {"role": "assistant", "content": "I found a list." + ("x" * 120)},
            {"role": "user", "content": "complete the sixth item from before"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=40)
        )
        payload = {
            "tool_name": "list_todos",
            "summary": {"count": 10},
            "full_result": {
                "ok": True,
                "todos": [{"id": 6, "title": "sixth"}],
            },
        }

        with patch(
            "app.context.context_index.read_context_ref",
            return_value=payload,
        ) as read_ref:
            assembly = engine.assemble(messages)

        read_ref.assert_called_once_with("ctx_test")
        self.assertEqual(assembly.report["retrieved_ref_count"], 1)
        self.assertEqual(assembly.report["retrieved_refs"][0]["status"], "loaded")
        self.assertTrue(
            any(
                isinstance(message, dict)
                and "[Retrieved context ref]" in message.get("content", "")
                for message in assembly.input_messages
            )
        )

    def test_invalid_requested_ref_is_reported_but_not_inserted(self) -> None:
        messages = [
            {"role": "user", "content": "old note " + ("x" * 120)},
            {"role": "assistant", "content": "old answer " + ("x" * 120)},
            {"role": "user", "content": "open exact ref ctx_missing"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=40)
        )

        with patch(
            "app.context.context_index.read_context_ref",
            return_value=None,
        ) as read_ref:
            assembly = engine.assemble(messages)

        read_ref.assert_called_once_with("ctx_missing")
        self.assertEqual(assembly.report["retrieved_ref_count"], 0)
        self.assertEqual(
            assembly.report["retrieved_refs"],
            [
                {
                    "ref_id": "ctx_missing",
                    "reason": "current_request_requires_exact_fields",
                    "status": "rejected",
                }
            ],
        )
        self.assertIn(
            "context_ref_rejected",
            [
                diagnostic["code"]
                for diagnostic in assembly.report["inspection"]["diagnostics"]
            ],
        )
        self.assertFalse(
            any(
                isinstance(message, dict)
                and "[Retrieved context ref]" in message.get("content", "")
                for message in assembly.input_messages
            )
        )

    def test_inspector_reports_exact_request_without_retrieval_match(self) -> None:
        messages = [
            {"role": "user", "content": "old note " + ("x" * 120)},
            {"role": "assistant", "content": "old answer " + ("x" * 120)},
            {"role": "user", "content": "complete todo id 999"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=40)
        )

        assembly = engine.assemble(messages)

        inspection = assembly.report["inspection"]
        self.assertEqual(
            inspection["decisions"][-1]["status"],
            "no_match",
        )
        self.assertIn(
            "exact_request_without_retrieval_match",
            [diagnostic["code"] for diagnostic in inspection["diagnostics"]],
        )


if __name__ == "__main__":
    unittest.main()
