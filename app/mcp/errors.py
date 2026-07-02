from __future__ import annotations


class McpClientError(RuntimeError):
    """Base error for local MCP adapter failures."""

    code = "mcp_client_error"


class McpProtocolError(McpClientError):
    code = "mcp_protocol_error"


class McpServerUnavailableError(McpClientError):
    code = "mcp_server_unavailable"


class McpTimeoutError(McpClientError):
    code = "mcp_timeout"


class McpInvalidResponseError(McpClientError):
    code = "mcp_invalid_response"
