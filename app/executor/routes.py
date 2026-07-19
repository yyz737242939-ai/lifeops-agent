"""Pure conditional routes for the bounded Executor graph."""

from __future__ import annotations

from typing import Literal

from app.executor.models import ToolActionDecision
from app.executor.state import ExecutorState


def route_after_decision(state: ExecutorState) -> Literal["tool", "end"]:
    if state["result"] is not None:
        return "end"
    if isinstance(state["current_decision"], ToolActionDecision):
        return "tool"
    raise ValueError("a non-terminal decision must be a ToolActionDecision.")


def route_after_tool(state: ExecutorState) -> Literal["continue", "end"]:
    if state["result"] is not None:
        return "end"
    if not state["observations"]:
        raise ValueError("a Tool route requires an observation.")
    return "continue"
