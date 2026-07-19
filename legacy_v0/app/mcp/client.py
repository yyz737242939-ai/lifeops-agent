from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.mcp.errors import (
    McpInvalidResponseError,
    McpProtocolError,
    McpServerUnavailableError,
    McpTimeoutError,
)
from app.mcp.types import McpServerConfig, McpToolCallResult


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_TRACKING_SERVER = McpServerConfig(
    server_id="mock_package_tracking",
    command=(sys.executable, "-m", "mcp_servers.mock_package_server"),
    timeout_seconds=5.0,
)


class StdioMcpClient:
    """Minimal stdio JSON-RPC MCP client for local learning servers."""

    def __init__(
        self,
        config: McpServerConfig,
        *,
        cwd: Path = REPO_ROOT,
    ) -> None:
        self.config = config
        self.cwd = cwd

    def list_tools(self) -> list[dict[str, Any]]:
        responses = self._roundtrip(
            [
                self._request(1, "initialize", self._initialize_params()),
                self._request(2, "tools/list", {}),
            ]
        )
        result = self._result_for_id(responses, 2)
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise McpInvalidResponseError("tools/list response missing tools list")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> McpToolCallResult:
        responses = self._roundtrip(
            [
                self._request(1, "initialize", self._initialize_params()),
                self._request(
                    2,
                    "tools/call",
                    {"name": tool_name, "arguments": arguments},
                ),
            ]
        )
        result = self._result_for_id(responses, 2)
        content = result.get("content", [])
        if not isinstance(content, list):
            raise McpInvalidResponseError("tools/call response content must be a list")
        structured = result.get("structuredContent")
        if structured is not None and not isinstance(structured, dict):
            raise McpInvalidResponseError(
                "tools/call structuredContent must be an object"
            )
        return McpToolCallResult(
            server_id=self.config.server_id,
            tool_name=tool_name,
            content=tuple(item for item in content if isinstance(item, dict)),
            structured_content=structured,
            is_error=bool(result.get("isError", False)),
        )

    def _roundtrip(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stdin = "".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests)
        try:
            completed = subprocess.run(
                self.config.command,
                input=stdin,
                text=True,
                capture_output=True,
                cwd=self.cwd,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise McpTimeoutError(
                f"MCP server {self.config.server_id} timed out"
            ) from error
        except OSError as error:
            raise McpServerUnavailableError(
                f"MCP server {self.config.server_id} could not start: {error}"
            ) from error

        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise McpServerUnavailableError(
                f"MCP server {self.config.server_id} exited with code "
                f"{completed.returncode}: {stderr}"
            )

        responses: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise McpInvalidResponseError(
                    f"MCP server returned invalid JSON: {line}"
                ) from error
            if not isinstance(response, dict):
                raise McpInvalidResponseError("MCP response must be a JSON object")
            responses.append(response)
        return responses

    @staticmethod
    def _request(request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}

    @staticmethod
    def _initialize_params() -> dict[str, Any]:
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "lifeops-agent", "version": "0.1.0"},
        }

    @staticmethod
    def _result_for_id(responses: list[dict[str, Any]], request_id: int) -> dict[str, Any]:
        for response in responses:
            if response.get("id") != request_id:
                continue
            error = response.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "MCP protocol error")
                raise McpProtocolError(message)
            result = response.get("result")
            if not isinstance(result, dict):
                raise McpInvalidResponseError(
                    f"MCP response {request_id} missing object result"
                )
            return result
        raise McpInvalidResponseError(f"MCP response {request_id} was not returned")


def package_tracking_client() -> StdioMcpClient:
    return StdioMcpClient(PACKAGE_TRACKING_SERVER)
