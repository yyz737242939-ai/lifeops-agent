from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


ToolParameters = dict[str, Any]
ToolResult = dict[str, Any]


class ToolEffect(StrEnum):
    """Declare whether a tool can mutate external or persisted state."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolDefinition:
    """Registry entry shared by capability building and runtime execution."""

    name: str
    description: str
    parameters: ToolParameters
    function: Callable[..., ToolResult]
    effect: ToolEffect
    idempotent: bool
    retryable: bool
    timeout_seconds: float

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "effect": self.effect.value,
            "idempotent": self.idempotent,
            "retryable": self.retryable,
            "timeout_seconds": self.timeout_seconds,
        }


TOOLS: dict[str, ToolDefinition] = {}


def register_tool(
    name: str,
    description: str,
    parameters: ToolParameters,
    *,
    effect: ToolEffect = ToolEffect.READ,
    idempotent: bool = True,
    retryable: bool = True,
    timeout_seconds: float = 10.0,
) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult]]:
    """Register a business function with its model and runtime contract."""

    def decorator(function: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        TOOLS[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            function=function,
            effect=effect,
            idempotent=idempotent,
            retryable=retryable,
            timeout_seconds=timeout_seconds,
        )
        return function

    return decorator
