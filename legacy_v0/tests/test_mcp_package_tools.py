import json
import unittest

from app.tools.capability_builder import build_capabilities
from app.tools.tool import TOOLS, ToolEffect, call_tool


class McpPackageToolTests(unittest.TestCase):
    def test_package_mcp_tools_are_global_read_tools(self) -> None:
        capability = build_capabilities(())

        for tool_name in (
            "track_package_via_mcp",
            "list_package_updates_via_mcp",
            "estimate_delivery_window_via_mcp",
        ):
            with self.subTest(tool_name=tool_name):
                self.assertIn(tool_name, capability.allowed_tool_names)
                self.assertEqual(TOOLS[tool_name].effect, ToolEffect.READ)
                self.assertEqual(capability.capability_sources[tool_name], ("common",))

    def test_track_package_via_mcp_returns_structured_result(self) -> None:
        capability = build_capabilities(())

        result = json.loads(
            call_tool(
                "track_package_via_mcp",
                {"tracking_number": "PKG-001"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "track_package_via_mcp")
        self.assertEqual(result["mcp"]["server_id"], "mock_package_tracking")
        self.assertEqual(result["mcp"]["tool_name"], "track_package")
        self.assertEqual(result["result"]["tracking_number"], "PKG-001")
        self.assertEqual(result["result"]["status"], "in_transit")

    def test_list_package_updates_via_mcp_returns_history(self) -> None:
        capability = build_capabilities(())

        result = json.loads(
            call_tool(
                "list_package_updates_via_mcp",
                {"tracking_number": "PKG-002"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["mcp"]["tool_name"], "list_package_updates")
        self.assertEqual(len(result["result"]["updates"]), 2)

    def test_estimate_delivery_window_via_mcp_returns_window(self) -> None:
        capability = build_capabilities(())

        result = json.loads(
            call_tool(
                "estimate_delivery_window_via_mcp",
                {"tracking_number": "PKG-002"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["mcp"]["tool_name"], "estimate_delivery_window")
        self.assertEqual(result["result"]["estimated_delivery_window"], "16:00-20:00")

    def test_missing_package_via_mcp_is_normalized_not_found(self) -> None:
        capability = build_capabilities(())

        result = json.loads(
            call_tool(
                "track_package_via_mcp",
                {"tracking_number": "PKG-404"},
                allowed_tool_names=capability.allowed_tool_names,
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "not_found")
        self.assertEqual(result["error"]["code"], "package_not_found")
        self.assertEqual(result["mcp"]["tool_name"], "track_package")


if __name__ == "__main__":
    unittest.main()
