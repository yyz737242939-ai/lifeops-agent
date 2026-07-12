"""Request-local state primitives for runtime orchestration."""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from app.intent.models import IntentDecision
from app.policy.models import PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeResult
from app.skills.models import PromptContribution, SkillSelection


class GraphRoute(StrEnum):
    """Stable policy routes exposed by the runtime graph."""

    ALLOW = "allow"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    DENY = "deny"


class GraphState(TypedDict):
    """Small request-local state passed between orchestration nodes."""

    request: RuntimeRequest
    intent: IntentDecision | None
    policy: PolicyDecision | None
    route: GraphRoute | None
    skill_selection: SkillSelection | None
    prompt_contributions: list[PromptContribution]
    result: RuntimeResult | None
    error_code: str | None
    error_stage: str | None
    graph_path: list[str]
    trace_summary: list[str]


def create_graph_state(request: RuntimeRequest) -> GraphState:
    """Create the initial request-local state for one graph invocation."""

    return {
        "request": request,
        "intent": None,
        "policy": None,
        "route": None,
        "skill_selection": None,
        "prompt_contributions": [],
        "result": None,
        "error_code": None,
        "error_stage": None,
        "graph_path": [],
        "trace_summary": [],
    }


def append_graph_path(graph_path: list[str], step_name: str) -> list[str]:
    """Return a new graph path with one validated node or route name appended."""

    if not step_name.strip():
        raise ValueError("step_name must be non-empty.")
    return [*graph_path, step_name]
