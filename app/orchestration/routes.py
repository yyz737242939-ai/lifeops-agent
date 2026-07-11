"""Pure route selection for runtime orchestration."""

from __future__ import annotations

from app.orchestration.state import GraphRoute, GraphState
from app.policy.models import PolicyAction


def route_after_policy(state: GraphState) -> GraphRoute:
    """Map the existing PolicyDecision to one stable graph route."""

    policy = state["policy"]
    if policy is None:
        raise ValueError("policy must be available before route selection.")
    if policy.action == PolicyAction.ALLOW:
        return GraphRoute.ALLOW
    if policy.action == PolicyAction.REQUIRES_CONFIRMATION:
        return GraphRoute.REQUIRES_CONFIRMATION
    return GraphRoute.DENY
