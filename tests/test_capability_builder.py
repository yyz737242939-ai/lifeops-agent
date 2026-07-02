import unittest

from app.tools.capability_builder import (
    COMMON_TOOL_NAMES,
    SKILL_TOOL_NAMES,
    build_capabilities,
)
from app.tools.tool import TOOLS, ToolEffect


def _read_tools(tool_names: frozenset[str]) -> frozenset[str]:
    return frozenset(name for name in tool_names if TOOLS[name].effect == ToolEffect.READ)


class CapabilityBuilderTests(unittest.TestCase):
    def test_filters_write_tools_when_current_turn_did_not_authorize_them(self) -> None:
        result = build_capabilities(
            ("wellbeing", "activity"),
            authorized_write_tool_names=frozenset(),
        )

        self.assertNotIn("record_daily_state", result.allowed_tool_names)
        self.assertIn("get_daily_state", result.allowed_tool_names)
        self.assertIn("recommend_activities", result.allowed_tool_names)
        self.assertNotIn("save_memory", result.allowed_tool_names)
        self.assertNotIn("delete_memory", result.allowed_tool_names)
        self.assertIn("list_memories", result.allowed_tool_names)

    def test_single_skill_exposes_only_domain_and_common_tools(self) -> None:
        result = build_capabilities(("todo",))

        self.assertEqual(
            result.allowed_tool_names,
            _read_tools(COMMON_TOOL_NAMES | SKILL_TOOL_NAMES["todo"]),
        )
        self.assertTrue(result.allowed_tool_names.isdisjoint(SKILL_TOOL_NAMES["finance"]))
        self.assertTrue(result.allowed_tool_names.isdisjoint(SKILL_TOOL_NAMES["wellbeing"]))
        self.assertTrue(result.allowed_tool_names.isdisjoint(SKILL_TOOL_NAMES["activity"]))
        self.assertFalse(result.fallback_used)

    def test_news_skill_exposes_declared_reference_source_and_helper_tools(self) -> None:
        result = build_capabilities(("news",))

        self.assertEqual(
            result.allowed_tool_names,
            _read_tools(COMMON_TOOL_NAMES | SKILL_TOOL_NAMES["news"]),
        )
        self.assertEqual(
            SKILL_TOOL_NAMES["news"],
            frozenset(
                {
                    "read_skill_reference",
                    "fetch_news_source",
                    "run_news_helper",
                }
            ),
        )
        self.assertIn("read_skill_reference", result.allowed_tool_names)
        self.assertIn("fetch_news_source", result.allowed_tool_names)
        self.assertIn("run_news_helper", result.allowed_tool_names)
        self.assertFalse(result.fallback_used)

    def test_cross_domain_request_merges_tools_without_duplicates(self) -> None:
        result = build_capabilities(("todo", "finance", "todo"))
        schema_names = [schema["name"] for schema in result.tool_schemas]

        self.assertEqual(
            result.allowed_tool_names,
            _read_tools(
                COMMON_TOOL_NAMES
                | SKILL_TOOL_NAMES["todo"]
                | SKILL_TOOL_NAMES["finance"]
            ),
        )
        self.assertEqual(len(schema_names), len(set(schema_names)))
        self.assertEqual(set(schema_names), set(result.allowed_tool_names))
        self.assertEqual(result.capability_sources["list_todos"], ("todo",))
        self.assertEqual(result.capability_sources["check_budget"], ("finance",))
        self.assertEqual(result.capability_sources["read_context_ref"], ("common",))

    def test_all_skills_expose_every_registered_tool(self) -> None:
        write_tools = frozenset(
            name for name, tool in TOOLS.items() if tool.effect == ToolEffect.WRITE
        )
        result = build_capabilities(
            tuple(SKILL_TOOL_NAMES),
            authorized_write_tool_names=write_tools,
        )

        self.assertEqual(result.allowed_tool_names, frozenset(TOOLS))
        self.assertEqual(result.schema_count, len(TOOLS))
        self.assertGreater(result.schema_chars, 0)

    def test_no_skill_uses_safe_common_tool_fallback(self) -> None:
        result = build_capabilities(())

        self.assertEqual(result.allowed_tool_names, _read_tools(COMMON_TOOL_NAMES))
        self.assertTrue(result.fallback_used)
        self.assertIn("read_context_ref", result.allowed_tool_names)
        self.assertIn("list_memories", result.allowed_tool_names)
        self.assertNotIn("save_memory", result.allowed_tool_names)

    def test_schema_order_follows_stable_registry_order(self) -> None:
        result = build_capabilities(("finance", "todo"))
        expected = [name for name in TOOLS if name in result.allowed_tool_names]

        self.assertEqual(
            [schema["name"] for schema in result.tool_schemas],
            expected,
        )

    def test_unknown_skill_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown skills"):
            build_capabilities(("missing-skill",))

    def test_authorized_common_memory_writes_are_exposed(self) -> None:
        result = build_capabilities(
            (),
            authorized_write_tool_names=frozenset({"save_memory", "delete_memory"}),
        )

        self.assertIn("save_memory", result.allowed_tool_names)
        self.assertIn("delete_memory", result.allowed_tool_names)
        self.assertIn("list_memories", result.allowed_tool_names)


if __name__ == "__main__":
    unittest.main()
