import json
import unittest
from unittest.mock import patch

from app.tools.capability_builder import build_capabilities
from app.tools.tool import call_tool


class ToolAuthorizationTests(unittest.TestCase):
    def test_authorized_tool_executes_normally(self) -> None:
        capability = build_capabilities(("todo",))

        result = json.loads(
            call_tool(
                "get_current_time",
                {},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "get_current_time")

    def test_unauthorized_tool_is_rejected_without_execution(self) -> None:
        capability = build_capabilities(("todo",))

        with patch("app.tools.tool.expense_store.add_expense") as add_expense:
            result = json.loads(
                call_tool(
                    "record_expense",
                    {
                        "amount": 35,
                        "category": "food",
                        "description": "lunch",
                    },
                    allowed_tool_names=capability.allowed_tool_names,
                )
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "tool_not_allowed")
        self.assertNotIn("record_expense", result["allowed_tools"])
        add_expense.assert_not_called()

    def test_unknown_tool_remains_distinct_from_denied_tool(self) -> None:
        result = json.loads(
            call_tool(
                "does_not_exist",
                {},
                allowed_tool_names=frozenset(),
            )
        )

        self.assertEqual(result["error"], "tool_not_found")


if __name__ == "__main__":
    unittest.main()
