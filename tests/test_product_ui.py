import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import app.product_ui.server as product_server
from app.memory.memory_store import SemanticMemoryStore
from app.product_ui.server import handle_api_request


class ProductUiTests(unittest.TestCase):
    def test_initial_state_returns_product_sections(self) -> None:
        with self._patched_data_files():
            payload, status = handle_api_request("GET", "/api/state")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("dashboard", payload)
        self.assertIn("todos", payload)
        self.assertIn("wellbeing", payload)
        self.assertIn("finance", payload)
        self.assertIn("activities", payload)
        self.assertIn("memories", payload)

    def test_creates_and_completes_todo_through_api(self) -> None:
        with self._patched_data_files():
            created, create_status = handle_api_request(
                "POST",
                "/api/todos",
                {"title": "Plan product UI", "priority": "high"},
            )
            completed, complete_status = handle_api_request(
                "POST",
                f"/api/todos/{created['todo']['id']}/complete",
            )
            state, _ = handle_api_request("GET", "/api/state")

        self.assertEqual(create_status, HTTPStatus.CREATED)
        self.assertEqual(complete_status, HTTPStatus.OK)
        self.assertEqual(completed["todo"]["status"], "done")
        self.assertEqual(state["dashboard"]["open_todo_count"], 0)

    def test_updates_todo_through_api(self) -> None:
        with self._patched_data_files():
            created, _ = handle_api_request(
                "POST",
                "/api/todos",
                {"title": "Draft UI", "priority": "medium"},
            )
            updated, status = handle_api_request(
                "PATCH",
                f"/api/todos/{created['todo']['id']}",
                {
                    "title": "Polish UI",
                    "priority": "high",
                    "due_date": "2026-07-03",
                },
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(updated["todo"]["title"], "Polish UI")
        self.assertEqual(updated["todo"]["priority"], "high")
        self.assertEqual(updated["todo"]["due_date"], "2026-07-03")

    def test_records_wellbeing_and_expense(self) -> None:
        with self._patched_data_files():
            log, log_status = handle_api_request(
                "POST",
                "/api/wellbeing",
                {
                    "log_date": "2026-07-02",
                    "sleep_hours": 7.5,
                    "mood": "good",
                    "energy": "medium",
                    "note": "Steady day",
                },
            )
            expense, expense_status = handle_api_request(
                "POST",
                "/api/expenses",
                {
                    "amount": 12.5,
                    "category": "food",
                    "description": "Lunch",
                    "spent_date": "2026-07-02",
                },
            )

        self.assertEqual(log_status, HTTPStatus.CREATED)
        self.assertEqual(log["log"]["mood"], "good")
        self.assertEqual(expense_status, HTTPStatus.CREATED)
        self.assertEqual(expense["finance"]["summary"]["total_amount"], 12.5)

    def test_queries_wellbeing_range(self) -> None:
        with self._patched_data_files():
            handle_api_request(
                "POST",
                "/api/wellbeing",
                {
                    "log_date": "2026-07-01",
                    "sleep_hours": 6.5,
                    "mood": "neutral",
                    "energy": "medium",
                },
            )
            handle_api_request(
                "POST",
                "/api/wellbeing",
                {
                    "log_date": "2026-07-02",
                    "sleep_hours": 7.5,
                    "mood": "good",
                    "energy": "high",
                },
            )
            payload, status = handle_api_request(
                "POST",
                "/api/wellbeing/query",
                {"days": 1, "end_date": "2026-07-02"},
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(len(payload["wellbeing"]["logs"]), 1)
        self.assertEqual(payload["wellbeing"]["logs"][0]["log_date"], "2026-07-02")

    def test_filters_finance_and_checks_budget(self) -> None:
        with self._patched_data_files():
            handle_api_request(
                "POST",
                "/api/expenses",
                {
                    "amount": 12.5,
                    "category": "food",
                    "description": "Lunch",
                    "spent_date": "2026-07-02",
                },
            )
            handle_api_request(
                "POST",
                "/api/expenses",
                {
                    "amount": 8,
                    "category": "transport",
                    "description": "Subway",
                    "spent_date": "2026-07-02",
                },
            )
            filtered, filter_status = handle_api_request(
                "POST",
                "/api/finance/query",
                {"category": "food", "start_date": "2026-07-01", "end_date": "2026-07-03"},
            )
            budget, budget_status = handle_api_request(
                "POST",
                "/api/budgets",
                {"category": "food", "amount": 20, "period": "weekly"},
            )
            checked, check_status = handle_api_request(
                "POST",
                "/api/budgets/check",
                {"category": "food", "period": "weekly"},
            )

        self.assertEqual(filter_status, HTTPStatus.OK)
        self.assertEqual(filtered["finance"]["summary"]["count"], 1)
        self.assertEqual(filtered["finance"]["summary"]["total_amount"], 12.5)
        self.assertEqual(budget_status, HTTPStatus.CREATED)
        self.assertEqual(budget["budget"]["amount"], 20)
        self.assertEqual(check_status, HTTPStatus.OK)
        self.assertEqual(checked["budget_status"]["spent"], 12.5)
        self.assertEqual(checked["budget_status"]["remaining"], 7.5)

    def test_recommends_activities(self) -> None:
        with self._patched_data_files():
            payload, status = handle_api_request(
                "POST",
                "/api/activities/recommend",
                {
                    "energy": "low",
                    "mood": "neutral",
                    "budget_level": "free",
                    "available_minutes": 30,
                    "location": "home",
                    "goal": "recover",
                },
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(payload["activities"])
        self.assertLessEqual(payload["activities"][0]["duration_minutes"], 30)

    def test_rejects_invalid_todo(self) -> None:
        with self._patched_data_files():
            payload, status = handle_api_request(
                "POST",
                "/api/todos",
                {"title": ""},
            )

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("error", payload)

    def test_agent_chat_returns_answer_and_run_state(self) -> None:
        with self._patched_data_files(), patch(
            "app.product_ui.server.Agent",
            FakeAgent,
        ):
            product_server._agent = None
            payload, status = handle_api_request(
                "POST",
                "/api/agent/chat",
                {"message": "What should I do next?"},
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["answer"], "Fake answer: What should I do next?")
        self.assertEqual(payload["run_state"]["status"], "completed")
        self.assertEqual(payload["run_state"]["successful_actions"], 1)
        self.assertEqual(payload["run_state"]["actions"][0]["tool_name"], "add_todo")
        self.assertEqual(len(payload["run_state"]["write_actions"]), 1)
        self.assertIn("state", payload)

    def test_agent_chat_rejects_empty_message(self) -> None:
        payload, status = handle_api_request(
            "POST",
            "/api/agent/chat",
            {"message": "  "},
        )

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("Message cannot be empty", payload["error"])

    def test_agent_reset_replaces_product_agent(self) -> None:
        with patch("app.product_ui.server.Agent", FakeAgent):
            product_server._agent = FakeAgent()
            payload, status = handle_api_request("POST", "/api/agent/reset")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(payload["reset"])
        self.assertIsInstance(product_server._agent, FakeAgent)

    def test_lists_and_deletes_memories(self) -> None:
        with self._patched_data_files() as root:
            store = SemanticMemoryStore(root / "semantic_memories.json")
            memory = store.save_memory(
                memory_type="preference",
                content="Prefers morning planning",
                tags=["planning"],
            )
            listed, list_status = handle_api_request(
                "POST",
                "/api/memories/query",
                {"type": "preference", "tag": "planning"},
            )
            deleted, delete_status = handle_api_request(
                "POST",
                f"/api/memories/{memory.id}/delete",
            )

        self.assertEqual(list_status, HTTPStatus.OK)
        self.assertEqual(listed["memories"]["items"][0]["id"], memory.id)
        self.assertEqual(delete_status, HTTPStatus.OK)
        self.assertEqual(deleted["memory"]["status"], "deleted")
        self.assertEqual(deleted["memories"]["items"], [])

    def _patched_data_files(self):
        temporary_directory = tempfile.TemporaryDirectory()
        root = Path(temporary_directory.name)
        patches = [
            patch("app.domains.todo_store.TODOS_FILE", root / "todos.json"),
            patch("app.domains.daily_log_store.DAILY_LOGS_FILE", root / "daily_logs.json"),
            patch("app.domains.expense_store.EXPENSES_FILE", root / "expenses.json"),
            patch("app.domains.expense_store.BUDGETS_FILE", root / "budgets.json"),
            patch(
                "app.memory.memory_store.SEMANTIC_MEMORIES_FILE",
                root / "semantic_memories.json",
            ),
        ]

        class PatchContext:
            def __enter__(self_inner):
                self_inner.stack = temporary_directory
                self_inner.patchers = [item.__enter__() for item in patches]
                return root

            def __exit__(self_inner, exc_type, exc, tb):
                for item in reversed(patches):
                    item.__exit__(exc_type, exc, tb)
                temporary_directory.cleanup()
                return False

        return PatchContext()


class FakeActionRecord:
    status = product_server.ActionStatus.COMPLETED
    tool_name = "add_todo"


class FakeStatus:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeRunState:
    run_id = "run_fake"
    status = FakeStatus("completed")
    stop_reason = FakeStatus("completed")
    chat_llm_round_count = 1
    chat_llm_request_count = 1
    chat_tool_execution_attempt_count = 1
    action_records = [FakeActionRecord()]


class FakeAgent:
    def __init__(self) -> None:
        self.last_run_state = None

    def chat(self, user_input: str) -> str:
        self.last_run_state = FakeRunState()
        return f"Fake answer: {user_input}"


if __name__ == "__main__":
    unittest.main()
