from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.integrations.mcp.errors import (
    McpProtocolError,
    McpResultInvalidError,
    McpServerUnavailableError,
    McpSyncBridgeError,
    McpTimeoutError,
    McpToolFailedError,
    McpToolSchemaMismatchError,
)
from app.integrations.mcp.models import McpServerConfig, McpToolCallResult


class McpContractTest(unittest.TestCase):
    def test_server_config_is_strict_and_bounded(self) -> None:
        config = McpServerConfig(
            server_id="huggingface-papers",
            command="python",
            args=("-m", "app.integrations.research_mcp.server"),
            cwd=Path("."),
            timeout_seconds=5.0,
        )

        self.assertEqual(config.server_id, "huggingface-papers")
        self.assertEqual(config.args[0], "-m")
        with self.assertRaises(ValueError):
            McpServerConfig("", "python")
        with self.assertRaises(ValueError):
            McpServerConfig("server", "python", args=["-m"])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            McpServerConfig("server", "python", timeout_seconds=0)

    def test_normalized_result_does_not_alias_caller_payload(self) -> None:
        payload = {"papers": [{"paper_id": "2601.00001"}]}
        result = McpToolCallResult(
            server_id="huggingface-papers",
            tool_name="search_papers",
            structured_content=payload,
        )

        payload["papers"].append({"paper_id": "2601.00002"})

        self.assertEqual(
            result.structured_content,
            {"papers": [{"paper_id": "2601.00001"}]},
        )

    def test_error_codes_and_retryability_are_stable(self) -> None:
        expected = (
            (McpServerUnavailableError, "mcp_server_unavailable", True),
            (McpTimeoutError, "mcp_timeout", True),
            (McpProtocolError, "mcp_protocol_error", False),
            (McpToolSchemaMismatchError, "mcp_tool_schema_mismatch", False),
            (McpToolFailedError, "mcp_tool_failed", False),
            (McpResultInvalidError, "mcp_result_invalid", False),
            (McpSyncBridgeError, "mcp_sync_bridge_unavailable", False),
        )

        for error_type, code, retryable in expected:
            with self.subTest(error_type=error_type.__name__):
                error = error_type("Safe MCP failure.")
                self.assertEqual(error.code, code)
                self.assertEqual(error.retryable, retryable)
                self.assertEqual(str(error), "Safe MCP failure.")

    def test_generic_mcp_boundary_does_not_import_runtime_or_domains(self) -> None:
        forbidden = (
            "app.domains",
            "app.executor",
            "app.orchestration",
            "app.planning",
            "app.policy",
            "app.runtime",
            "app.storage",
            "app.tools",
            "huggingface_hub",
        )
        violations: list[str] = []
        for path in sorted(Path("app/integrations/mcp").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported = (node.module,)
                for name in imported:
                    if name.startswith(forbidden):
                        violations.append(f"{path}:{name}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
