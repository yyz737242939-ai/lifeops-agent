from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from app.integrations.mcp.client import OneShotStdioMcpClient
from app.integrations.mcp.errors import (
    McpServerUnavailableError,
    McpSyncBridgeError,
    McpToolSchemaMismatchError,
    McpResultInvalidError,
    McpTimeoutError,
    McpToolFailedError,
)
from app.integrations.mcp.models import McpServerConfig


ECHO_INPUT_SCHEMA = {
    "properties": {"value": {"title": "Value", "type": "string"}},
    "required": ["value"],
    "title": "echoArguments",
    "type": "object",
}
NO_ARGUMENTS_SCHEMA = {
    "properties": {},
    "title": "get_pidArguments",
    "type": "object",
}


class OneShotStdioMcpClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = OneShotStdioMcpClient()
        self.config = McpServerConfig(
            server_id="test-echo",
            command=sys.executable,
            args=("-m", "tests.fixtures.mcp.echo_server"),
            cwd=Path.cwd(),
            timeout_seconds=5.0,
        )

    def test_real_stdio_server_is_initialized_called_and_closed(self) -> None:
        result = self.client.call_tool(
            self.config,
            tool_name="echo",
            arguments={"value": "hello"},
            expected_input_schema=ECHO_INPUT_SCHEMA,
        )

        self.assertEqual(result.structured_content, {"value": "hello"})
        self.assertFalse(result.is_error)

    def test_tool_schema_must_match_exactly(self) -> None:
        with self.assertRaises(McpToolSchemaMismatchError):
            self.client.call_tool(
                self.config,
                tool_name="echo",
                arguments={"value": "hello"},
                expected_input_schema={"type": "object"},
            )

    def test_process_start_failure_is_safe_and_typed(self) -> None:
        config = McpServerConfig(
            server_id="missing",
            command="lifeops-command-that-does-not-exist",
            cwd=Path.cwd(),
            timeout_seconds=1.0,
        )

        with self.assertRaises(McpServerUnavailableError) as caught:
            self.client.call_tool(
                config,
                tool_name="echo",
                arguments={"value": "hello"},
                expected_input_schema=ECHO_INPUT_SCHEMA,
            )

        self.assertNotIn("lifeops-command", str(caught.exception))

    def test_sync_bridge_rejects_an_active_event_loop(self) -> None:
        async def call_inside_loop() -> None:
            with self.assertRaises(McpSyncBridgeError):
                self.client.call_tool(
                    self.config,
                    tool_name="echo",
                    arguments={"value": "hello"},
                    expected_input_schema=ECHO_INPUT_SCHEMA,
                )

        asyncio.run(call_inside_loop())

    def test_timeout_tool_error_and_invalid_result_are_distinct(self) -> None:
        config = McpServerConfig(
            server_id="failure-fixture",
            command=sys.executable,
            args=("-m", "tests.fixtures.mcp.failure_server"),
            cwd=Path.cwd(),
            timeout_seconds=3.0,
        )
        cases = (
            ("slow", McpTimeoutError),
            ("fail", McpToolFailedError),
            ("plain", McpResultInvalidError),
        )
        for tool_name, error_type in cases:
            with self.subTest(tool_name=tool_name):
                current_config = config
                if tool_name == "slow":
                    current_config = McpServerConfig(
                        server_id="failure-fixture",
                        command=sys.executable,
                        args=("-m", "tests.fixtures.mcp.failure_server"),
                        cwd=Path.cwd(),
                        timeout_seconds=1.5,
                    )
                with self.assertRaises(error_type):
                    self.client.call_tool(
                        current_config,
                        tool_name=tool_name,
                        arguments={"value": "private query"},
                        expected_input_schema={
                            "properties": {
                                "value": {"title": "Value", "type": "string"}
                            },
                            "required": ["value"],
                            "title": f"{tool_name}Arguments",
                            "type": "object",
                        },
                    )

    def test_unexpected_server_exit_is_unavailable(self) -> None:
        config = McpServerConfig(
            server_id="exit-fixture",
            command=sys.executable,
            args=("-m", "tests.fixtures.mcp.exit_server"),
            cwd=Path.cwd(),
            timeout_seconds=1.0,
        )
        with self.assertRaises(McpServerUnavailableError):
            self.client.call_tool(
                config,
                tool_name="missing",
                arguments={},
                expected_input_schema={
                    "properties": {},
                    "title": "missingArguments",
                    "type": "object",
                },
            )

    def test_server_process_is_gone_after_successful_close(self) -> None:
        config = McpServerConfig(
            server_id="pid-fixture",
            command=sys.executable,
            args=("-m", "tests.fixtures.mcp.failure_server"),
            cwd=Path.cwd(),
            timeout_seconds=3.0,
        )
        result = self.client.call_tool(
            config,
            tool_name="get_pid",
            arguments={},
            expected_input_schema=NO_ARGUMENTS_SCHEMA,
        )
        pid = int(result.structured_content["pid"])
        for _ in range(20):
            if not _process_exists(pid):
                break
            time.sleep(0.05)

        self.assertFalse(_process_exists(pid))

    def test_server_process_is_gone_after_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "server.pid"
            config = McpServerConfig(
                server_id="timeout-pid-fixture",
                command=sys.executable,
                args=(
                    "-m",
                    "tests.fixtures.mcp.failure_server",
                    "--pid-file",
                    str(pid_file),
                ),
                cwd=Path.cwd(),
                timeout_seconds=1.5,
            )
            with self.assertRaises(McpTimeoutError):
                self.client.call_tool(
                    config,
                    tool_name="slow",
                    arguments={"value": "hello"},
                    expected_input_schema={
                        "properties": {
                            "value": {"title": "Value", "type": "string"}
                        },
                        "required": ["value"],
                        "title": "slowArguments",
                        "type": "object",
                    },
                )
            pid = int(pid_file.read_text(encoding="utf-8"))
            for _ in range(20):
                if not _process_exists(pid):
                    break
                time.sleep(0.05)

            self.assertFalse(_process_exists(pid))

    def test_application_log_omits_arguments_and_provider_text(self) -> None:
        with self.assertLogs("app.integrations.mcp.client", level="INFO") as captured:
            self.client.call_tool(
                self.config,
                tool_name="echo",
                arguments={"value": "private research query"},
                expected_input_schema=ECHO_INPUT_SCHEMA,
            )

        joined = "\n".join(captured.output)
        self.assertIn("server_id=test-echo", joined)
        self.assertIn("tool_name=echo", joined)
        self.assertNotIn("private research query", joined)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


if __name__ == "__main__":
    unittest.main()
