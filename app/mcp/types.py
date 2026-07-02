from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class McpServerConfig:
    """How the local Agent launches one MCP server."""

    server_id: str
    command: tuple[str, ...]
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class McpToolCallResult:
    """Normalized result from an MCP tools/call response."""

    server_id: str
    tool_name: str
    content: tuple[dict[str, Any], ...]
    structured_content: dict[str, Any] | None
    is_error: bool
