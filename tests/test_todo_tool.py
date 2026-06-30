import unittest
from unittest.mock import patch

from app.memory.todo_store import Todo
from app.tools.tool import list_todos, read_context_ref


class TodoToolTests(unittest.TestCase):
    @patch("app.tools.tool.todo_store.list_todos")
    def test_list_todos_supports_limit_status_and_sort(self, list_store_todos) -> None:
        list_store_todos.return_value = [
            Todo(id=1, title="low", status="todo", priority="low"),
            Todo(id=2, title="done", status="done", priority="high"),
            Todo(id=3, title="high", status="todo", priority="high"),
            Todo(id=4, title="medium", status="todo", priority="medium"),
        ]

        result = list_todos(limit=2, status="todo", sort="priority_due")

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 2)
        self.assertEqual([todo["id"] for todo in result["todos"]], [3, 4])

    @patch("app.tools.tool.todo_store.list_todos")
    def test_list_todos_rejects_invalid_limit(self, list_store_todos) -> None:
        list_store_todos.return_value = []

        result = list_todos(limit=0)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "limit_must_be_at_least_1")

    @patch("app.tools.tool.load_context_ref")
    def test_read_context_ref_returns_metadata(self, load_context_ref) -> None:
        load_context_ref.return_value = {
            "tool_name": "list_todos",
            "created_at": "2026-06-30T10:00:00",
            "expires_at": "2026-07-07T10:00:00",
            "payload_hash": "abc123",
            "summary": {"count": 1},
            "full_result": {"ok": True},
        }

        result = read_context_ref("ctx_test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["created_at"], "2026-06-30T10:00:00")
        self.assertEqual(result["expires_at"], "2026-07-07T10:00:00")
        self.assertEqual(result["payload_hash"], "abc123")


if __name__ == "__main__":
    unittest.main()
