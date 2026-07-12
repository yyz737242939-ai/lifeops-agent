"""Request-local Tool runtime construction primitives."""

from __future__ import annotations

from dataclasses import dataclass

from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ToolRuntime:
    """Registry and Gateway that share request-local handler instances."""

    registry: ToolRegistry
    gateway: ToolGateway

    @classmethod
    def from_registry(cls, registry: ToolRegistry) -> "ToolRuntime":
        return cls(registry=registry, gateway=ToolGateway(registry))
