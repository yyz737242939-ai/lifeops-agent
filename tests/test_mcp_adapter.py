import unittest

from app.mcp.client import package_tracking_client
from app.mcp.errors import McpProtocolError


class McpAdapterTests(unittest.TestCase):
    def test_lists_mock_package_tools(self) -> None:
        tools = package_tracking_client().list_tools()

        self.assertEqual(
            {tool["name"] for tool in tools},
            {
                "track_package",
                "list_package_updates",
                "estimate_delivery_window",
            },
        )

    def test_calls_mock_package_tool(self) -> None:
        result = package_tracking_client().call_tool(
            "track_package",
            {"tracking_number": "PKG-001"},
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.server_id, "mock_package_tracking")
        self.assertEqual(result.tool_name, "track_package")
        self.assertEqual(result.structured_content["tracking_number"], "PKG-001")

    def test_unknown_tool_becomes_protocol_error(self) -> None:
        with self.assertRaisesRegex(McpProtocolError, "Unknown tool"):
            package_tracking_client().call_tool("missing_tool", {})


if __name__ == "__main__":
    unittest.main()
