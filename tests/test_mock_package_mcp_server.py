import unittest

from mcp_servers.mock_package_server import handle_request, load_shipments


class MockPackageMcpServerTests(unittest.TestCase):
    def test_loads_mock_shipments(self) -> None:
        shipments = load_shipments()

        self.assertGreaterEqual(len(shipments), 2)
        self.assertEqual(shipments[0]["tracking_number"], "PKG-001")

    def test_initialize_declares_tools_capability(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

        self.assertEqual(response["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(response["result"]["serverInfo"]["name"], "lifeops-mock-package-tracking")

    def test_lists_package_tools(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        tool_names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertEqual(
            tool_names,
            {
                "track_package",
                "list_package_updates",
                "estimate_delivery_window",
            },
        )

    def test_tracks_package_with_structured_content(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "track_package",
                    "arguments": {"tracking_number": "PKG-001"},
                },
            }
        )

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["tracking_number"], "PKG-001")
        self.assertEqual(result["structuredContent"]["status"], "in_transit")

    def test_lists_package_updates(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "list_package_updates",
                    "arguments": {"tracking_number": "PKG-002"},
                },
            }
        )

        result = response["result"]["structuredContent"]
        self.assertEqual(result["tracking_number"], "PKG-002")
        self.assertEqual(len(result["updates"]), 2)

    def test_estimates_delivery_window(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "estimate_delivery_window",
                    "arguments": {"tracking_number": "PKG-002"},
                },
            }
        )

        result = response["result"]["structuredContent"]
        self.assertEqual(result["estimated_delivery_date"], "2026-07-02")
        self.assertEqual(result["estimated_delivery_window"], "16:00-20:00")

    def test_unknown_tool_is_protocol_error(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "unknown", "arguments": {}},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("Unknown tool", response["error"]["message"])

    def test_missing_tracking_number_is_protocol_error(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "track_package", "arguments": {}},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("tracking_number", response["error"]["message"])

    def test_missing_package_is_tool_error_result(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "track_package",
                    "arguments": {"tracking_number": "PKG-404"},
                },
            }
        )

        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "package_not_found")


if __name__ == "__main__":
    unittest.main()
