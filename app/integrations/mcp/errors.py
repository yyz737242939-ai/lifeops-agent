"""Safe typed failures for MCP client and transport boundaries."""

from __future__ import annotations


class McpClientError(Exception):
    """Base failure with a stable code and retryability contract."""

    code = "mcp_client_error"
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class McpServerUnavailableError(McpClientError):
    code = "mcp_server_unavailable"
    retryable = True


class McpTimeoutError(McpClientError):
    code = "mcp_timeout"
    retryable = True


class McpProtocolError(McpClientError):
    code = "mcp_protocol_error"


class McpToolSchemaMismatchError(McpClientError):
    code = "mcp_tool_schema_mismatch"


class McpToolFailedError(McpClientError):
    code = "mcp_tool_failed"


class McpResultInvalidError(McpClientError):
    code = "mcp_result_invalid"


class McpSyncBridgeError(McpClientError):
    code = "mcp_sync_bridge_unavailable"
