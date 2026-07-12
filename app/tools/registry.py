"""In-memory Tool definition and handler registry."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.common.validation import require_non_empty_string
from app.tools.errors import ToolNotFoundError, ToolRegistryError
from app.tools.models import ToolDefinition, ToolResult
from app.tools.schema import validate_tool_schema


ToolHandler = Callable[[dict[str, Any]], ToolResult]


@dataclass(frozen=True)
class RegisteredTool:
    """One validated Tool contract bound to its runtime handler."""

    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    """Validated startup registry used by authorization and gateway layers."""

    def __init__(
        self,
        tools: Iterable[tuple[ToolDefinition, ToolHandler]] = (),
    ) -> None:
        self._by_name: dict[str, RegisteredTool] = {}
        for definition, handler in tools:
            self.register(definition, handler)

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        """Validate and bind one Tool definition exactly once."""

        if not isinstance(definition, ToolDefinition):
            raise ToolRegistryError(
                "Tool registry only accepts ToolDefinition values.",
                code="tool_registry_invalid_definition",
            )
        if not callable(handler):
            raise ToolRegistryError(
                "Tool handler must be callable.",
                code="tool_registry_invalid_handler",
                details={"tool_name": definition.name},
            )
        if definition.name in self._by_name:
            raise ToolRegistryError(
                f"Duplicate Tool name: {definition.name}",
                code="tool_registry_duplicate_name",
                details={"tool_name": definition.name},
            )

        validate_tool_schema(definition.input_schema, "input_schema")
        validate_tool_schema(definition.output_schema, "output_schema")
        self._by_name[definition.name] = RegisteredTool(definition, handler)

    def get(self, tool_name: str) -> ToolDefinition:
        """Return one registered definition without exposing its handler."""

        return self.resolve(tool_name).definition

    def resolve(self, tool_name: str) -> RegisteredTool:
        """Resolve definition and handler for the future Tool Gateway."""

        try:
            require_non_empty_string(tool_name, "tool_name")
        except ValueError as exc:
            raise ToolRegistryError(
                str(exc), code="tool_registry_invalid_name"
            ) from exc
        try:
            return self._by_name[tool_name]
        except KeyError as exc:
            raise ToolNotFoundError(
                f"Tool is not registered: {tool_name}",
                code="tool_not_found",
                details={"tool_name": tool_name},
            ) from exc

    def list_definitions(self) -> tuple[ToolDefinition, ...]:
        """Return definitions in deterministic Tool name order."""

        return tuple(self._by_name[name].definition for name in sorted(self._by_name))

    def model_catalog(
        self, tool_names: Iterable[str] | None = None
    ) -> tuple[dict[str, Any], ...]:
        """Return a minimal model catalog, optionally limited by authorization."""

        allowed_names = None if tool_names is None else set(tool_names)
        if allowed_names is not None:
            for tool_name in allowed_names:
                self.get(tool_name)
        return tuple(
            {
                "name": definition.name,
                "description": definition.description,
                "input_schema": deepcopy(definition.input_schema),
            }
            for definition in self.list_definitions()
            if allowed_names is None or definition.name in allowed_names
        )

    def contains(self, tool_name: str) -> bool:
        return tool_name in self._by_name

    def __len__(self) -> int:
        return len(self._by_name)
