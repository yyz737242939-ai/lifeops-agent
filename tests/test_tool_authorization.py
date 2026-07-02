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
        self.assertEqual(result["error"]["type"], "permission_denied")
        self.assertEqual(result["error"]["code"], "tool_not_allowed")
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

        self.assertEqual(result["error"]["type"], "not_found")
        self.assertEqual(result["error"]["code"], "tool_not_found")

    def test_skill_reference_requires_news_skill_capability(self) -> None:
        capability = build_capabilities(())

        result = json.loads(
            call_tool(
                "read_skill_reference",
                {"ref_id": "briefing_policy"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "permission_denied")
        self.assertEqual(result["error"]["code"], "tool_not_allowed")

    def test_skill_reference_reads_declared_news_markdown(self) -> None:
        capability = build_capabilities(("news",))

        result = json.loads(
            call_tool(
                "read_skill_reference",
                {"ref_id": "briefing_policy"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "read_skill_reference")
        self.assertEqual(result["skill"], "news")
        self.assertEqual(result["path"], "references/briefing_policy.md")
        self.assertIn("Briefing Policy", result["content"])

    def test_skill_reference_rejects_undeclared_ref_id(self) -> None:
        capability = build_capabilities(("news",))

        result = json.loads(
            call_tool(
                "read_skill_reference",
                {"ref_id": "../PROJECT_CONTEXT.md"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "not_found")
        self.assertEqual(result["error"]["code"], "skill_reference_not_found")

    def test_news_source_requires_news_skill_capability(self) -> None:
        capability = build_capabilities(())

        result = json.loads(
            call_tool(
                "fetch_news_source",
                {"source_id": "hf_blog"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "permission_denied")
        self.assertEqual(result["error"]["code"], "tool_not_allowed")

    def test_news_helper_requires_news_skill_capability(self) -> None:
        capability = build_capabilities(())

        result = json.loads(
            call_tool(
                "run_news_helper",
                {
                    "helper_id": "parse_hf_blog",
                    "arguments": {"html": "<html></html>", "limit": 1},
                },
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "permission_denied")
        self.assertEqual(result["error"]["code"], "tool_not_allowed")

    def test_news_helper_runs_declared_read_only_helper(self) -> None:
        capability = build_capabilities(("news",))

        result = json.loads(
            call_tool(
                "run_news_helper",
                {
                    "helper_id": "parse_hf_blog",
                    "arguments": {
                        "html": '<a href="/blog/test">Agent workflow update</a>',
                        "limit": 2,
                    },
                },
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "run_news_helper")
        self.assertEqual(result["result"][0]["source_id"], "hf_blog")


if __name__ == "__main__":
    unittest.main()
