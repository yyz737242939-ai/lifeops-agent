"""Minimal request-local state for the future Executor graph."""

from __future__ import annotations

from typing import Any, TypedDict

from app.executor.models import ExecutorDecision, ExecutorResult, ToolObservation
from app.runtime.models import RuntimeRequest
from app.skills.models import PromptContribution


class ExecutorState(TypedDict):
    """Internal state owned by one Executor invocation."""

    request: RuntimeRequest
    prompt_contributions: tuple[PromptContribution, ...]
    tool_catalog: tuple[dict[str, Any], ...]
    observations: list[ToolObservation]
    current_decision: ExecutorDecision | None
    step_count: int
    result: ExecutorResult | None
    error_code: str | None
    executor_path: list[str]


def create_executor_state(
    request: RuntimeRequest,
    *,
    prompt_contributions: tuple[PromptContribution, ...] = (),
    tool_catalog: tuple[dict[str, Any], ...] = (),
) -> ExecutorState:
    """Create isolated initial state for one Executor invocation."""

    if not isinstance(request, RuntimeRequest):
        raise ValueError("request must be a RuntimeRequest.")
    if not isinstance(prompt_contributions, tuple) or any(
        not isinstance(item, PromptContribution) for item in prompt_contributions
    ):
        raise ValueError(
            "prompt_contributions must contain PromptContribution values."
        )
    if not isinstance(tool_catalog, tuple) or any(
        not isinstance(item, dict) for item in tool_catalog
    ):
        raise ValueError("tool_catalog must contain dict values.")
    return {
        "request": request,
        "prompt_contributions": prompt_contributions,
        "tool_catalog": tool_catalog,
        "observations": [],
        "current_decision": None,
        "step_count": 0,
        "result": None,
        "error_code": None,
        "executor_path": [],
    }
