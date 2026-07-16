"""LifeOps-owned MCP configuration and normalized call results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.common.validation import require_non_empty_string


@dataclass(frozen=True)
class McpServerConfig:
    """How one local stdio MCP server is launched for a bounded call."""

    server_id: str
    command: str
    args: tuple[str, ...] = ()
    cwd: Path = field(default_factory=Path.cwd)
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        require_non_empty_string(self.server_id, "server_id")
        require_non_empty_string(self.command, "command")
        if not isinstance(self.args, tuple):
            raise ValueError("args must be a tuple.")
        for argument in self.args:
            require_non_empty_string(argument, "args")
        if not isinstance(self.cwd, Path):
            raise ValueError("cwd must be a pathlib.Path.")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive.")


@dataclass(frozen=True)
class McpToolCallResult:
    """Normalized MCP tools/call result without SDK content block types."""

    server_id: str
    tool_name: str
    structured_content: dict[str, Any]
    is_error: bool = False

    def __post_init__(self) -> None:
        require_non_empty_string(self.server_id, "server_id")
        require_non_empty_string(self.tool_name, "tool_name")
        if not isinstance(self.structured_content, dict):
            raise ValueError("structured_content must be an object.")
        if not isinstance(self.is_error, bool):
            raise ValueError("is_error must be a boolean.")
        object.__setattr__(
            self, "structured_content", deepcopy(self.structured_content)
        )
