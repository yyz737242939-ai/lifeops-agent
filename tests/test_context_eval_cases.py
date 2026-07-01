import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.context.context_budget import ContextBudgetConfig
from app.context.context_engine import ContextEngine
from app.utils.serialization import json_safe


def _call(name: str, call_id: str, arguments: str = "{}") -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=call_id,
    )


def _observation(call_id: str, payload: dict[str, object]) -> dict[str, str]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(payload, ensure_ascii=False),
    }


class ContextEvalCaseTests(unittest.TestCase):
    def test_exact_todo_followup_retrieves_only_related_evicted_unit(self) -> None:
        todo_call = _call("list_todos", "call-todo")
        todo_observation = _observation(
            "call-todo",
            {
                "ok": True,
                "action": "list_todos",
                "todos": [
                    {"id": 42, "title": "pay rent", "status": "todo"},
                    {"id": 77, "title": "book dentist", "status": "todo"},
                ],
            },
        )
        expense_call = _call("list_expenses", "call-expense")
        expense_observation = _observation(
            "call-expense",
            {
                "ok": True,
                "action": "list_expenses",
                "expenses": [
                    {
                        "id": "exp-1",
                        "amount": 38,
                        "date": "2026-06-30",
                        "description": "lunch",
                    }
                ],
            },
        )
        messages = [
            {"role": "user", "content": "old todo lookup " + ("x" * 160)},
            todo_call,
            todo_observation,
            {"role": "assistant", "content": "Task 42 is pay rent." + ("x" * 160)},
            {"role": "user", "content": "old expense lookup " + ("x" * 160)},
            expense_call,
            expense_observation,
            {"role": "assistant", "content": "Expense exp-1 was lunch." + ("x" * 160)},
            {"role": "user", "content": "complete todo id 42"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=45)
        )

        assembly = engine.assemble(messages)

        self.assertIn(todo_call, assembly.input_messages)
        self.assertIn(todo_observation, assembly.input_messages)
        self.assertNotIn(expense_call, assembly.input_messages)
        self.assertNotIn(expense_observation, assembly.input_messages)
        self.assertEqual(assembly.report["retrieved_unit_count"], 1)
        self.assertEqual(
            assembly.report["retrieved_units"][0]["reason"],
            "matched_entity_id",
        )
        self.assertIn(
            "entity_id",
            assembly.report["retrieved_units"][0]["matched_fields"],
        )

    def test_exact_expense_followup_restores_amount_and_date_context(self) -> None:
        expense_call = _call("list_expenses", "call-expense")
        expense_observation = _observation(
            "call-expense",
            {
                "ok": True,
                "action": "list_expenses",
                "expenses": [
                    {
                        "id": "exp-38",
                        "amount": 38,
                        "date": "2026-06-30",
                        "category": "food",
                        "description": "ramen",
                    }
                ],
            },
        )
        messages = [
            {"role": "user", "content": "list recent expenses " + ("x" * 180)},
            expense_call,
            expense_observation,
            {
                "role": "assistant",
                "content": "You had a 38 yuan food expense on 2026-06-30."
                + ("x" * 180),
            },
            {
                "role": "user",
                "content": "what was the exact amount and date for expense exp-38?",
            },
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=45)
        )

        assembly = engine.assemble(messages)

        self.assertIn(expense_call, assembly.input_messages)
        self.assertIn(expense_observation, assembly.input_messages)
        restored_text = json.dumps(json_safe(assembly.input_messages), ensure_ascii=False)
        self.assertIn("38", restored_text)
        self.assertIn("2026-06-30", restored_text)
        self.assertEqual(assembly.report["retrieved_unit_count"], 1)
        self.assertIn(
            "domain",
            assembly.report["retrieved_units"][0]["matched_fields"],
        )

    def test_failed_write_is_summarized_as_failure_not_success(self) -> None:
        add_call = _call("add_todo", "call-add", '{"title":"pay rent"}')
        failed_observation = _observation(
            "call-add",
            {
                "ok": False,
                "action": "add_todo",
                "error": {
                    "code": "validation_error",
                    "message": "title is required",
                },
            },
        )
        messages = [
            {"role": "user", "content": "please add a todo " + ("x" * 160)},
            add_call,
            failed_observation,
            {
                "role": "assistant",
                "content": "I could not save that todo." + ("x" * 160),
            },
            {"role": "user", "content": "new topic"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(
                recent_window_tokens=45,
                soft_limit_tokens=1,
            )
        )

        report = engine.after_turn(messages)

        self.assertTrue(report["compacted"])
        self.assertEqual(engine.store.summary["successful_actions"], [])
        self.assertEqual(
            engine.store.summary["failed_actions"],
            [
                {
                    "unit_id": "u_0002",
                    "tool_name": "add_todo",
                    "call_id": "call-add",
                    "action": "add_todo",
                    "error": {
                        "code": "validation_error",
                        "message": "title is required",
                    },
                }
            ],
        )

    def test_protected_pending_context_survives_windowing_and_hard_limit(self) -> None:
        pending_confirmation_note = {
            "role": "system",
            "content": (
                "Pending destructive request: user asked to delete all todos; "
                "explicit confirmation is still required."
            ),
        }
        messages = [pending_confirmation_note] + [
            {"role": "user", "content": f"filler {index} " + ("x" * 150)}
            for index in range(12)
        ]
        messages.append({"role": "user", "content": "continue"})
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(
                recent_window_tokens=40,
                hard_limit_tokens=60,
            )
        )

        assembly = engine.assemble(messages)

        self.assertIn(pending_confirmation_note, assembly.input_messages)
        self.assertGreater(assembly.report["protected_unit_count"], 0)
        self.assertTrue(assembly.report["passive_compaction"]["triggered"])
        protected_units = [
            unit for unit in assembly.report["units"] if unit["protected"]
        ]
        self.assertEqual(protected_units[0]["kind"], "system_note")

    def test_exact_ref_followup_uses_loaded_ref_without_reinserting_full_history(self) -> None:
        ref_call = _call("list_todos", "call-ref")
        ref_observation = _observation(
            "call-ref",
            {
                "ok": True,
                "compacted": True,
                "compaction_strategy": "summary_reference",
                "summary": {"count": 10},
                "ref_id": "ctx_eval",
            },
        )
        unrelated_call = _call("list_expenses", "call-unrelated")
        unrelated_observation = _observation(
            "call-unrelated",
            {
                "ok": True,
                "action": "list_expenses",
                "expenses": [{"id": "exp-1", "amount": 88}],
            },
        )
        messages = [
            {"role": "user", "content": "old todo list " + ("x" * 160)},
            ref_call,
            ref_observation,
            {"role": "assistant", "content": "I found ten todos." + ("x" * 160)},
            {"role": "user", "content": "old expenses " + ("x" * 160)},
            unrelated_call,
            unrelated_observation,
            {"role": "assistant", "content": "I found expenses." + ("x" * 160)},
            {"role": "user", "content": "complete the sixth item from before"},
        ]
        engine = ContextEngine(
            budget_config=ContextBudgetConfig(recent_window_tokens=45)
        )
        payload = {
            "tool_name": "list_todos",
            "summary": {"count": 10},
            "full_result": {
                "ok": True,
                "todos": [{"id": 6, "title": "sixth item"}],
            },
        }

        with patch(
            "app.context.context_index.read_context_ref",
            return_value=payload,
        ) as read_ref:
            assembly = engine.assemble(messages)

        read_ref.assert_called_once_with("ctx_eval")
        self.assertIn(ref_call, assembly.input_messages)
        self.assertIn(ref_observation, assembly.input_messages)
        self.assertNotIn(unrelated_call, assembly.input_messages)
        self.assertNotIn(unrelated_observation, assembly.input_messages)
        self.assertEqual(assembly.report["retrieved_ref_count"], 1)
        self.assertLess(
            assembly.report["assembled_message_count"],
            assembly.report["raw_message_count"],
        )
        self.assertIn("sixth item", json.dumps(json_safe(assembly.input_messages)))


if __name__ == "__main__":
    unittest.main()
