"""Request-local Tool authorization from Policy and registered contracts."""

from __future__ import annotations

from app.policy.models import PolicyAction, PolicyDecision
from app.tools.errors import ToolAuthorizationError
from app.tools.models import AllowedToolSet
from app.tools.registry import ToolRegistry


def resolve_allowed_tools(
    policy: PolicyDecision,
    registry: ToolRegistry,
) -> AllowedToolSet:
    """Resolve Policy-authorized Tool names against the startup registry."""

    if not isinstance(policy, PolicyDecision):
        raise ToolAuthorizationError(
            "policy must be a PolicyDecision.",
            code="tool_authorization_invalid_policy",
        )
    if not isinstance(registry, ToolRegistry):
        raise ToolAuthorizationError(
            "registry must be a ToolRegistry.",
            code="tool_authorization_invalid_registry",
        )
    if policy.action != PolicyAction.ALLOW:
        return AllowedToolSet()

    allowed_tool_names = set(policy.allowed_tools)
    unknown_allowed = sorted(
        name for name in allowed_tool_names if not registry.contains(name)
    )
    if unknown_allowed:
        raise ToolAuthorizationError(
            "Policy allowed_tools contains unregistered Tool names.",
            code="tool_authorization_unknown_allowed_tool",
            details={"tool_names": unknown_allowed},
        )

    selected_tools = tuple(
        definition
        for definition in registry.list_definitions()
        if definition.name in allowed_tool_names
    )
    return AllowedToolSet(
        tool_names=tuple(definition.name for definition in selected_tools),
    )
