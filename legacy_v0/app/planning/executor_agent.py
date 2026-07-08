"""Thin ExecutorAgent boundary for Plan and Execute v0."""

from dataclasses import dataclass
from typing import Any

from app.runtime.run_state import RunState


@dataclass(frozen=True)
class StepExecutionContext:
    """Inputs needed to execute one already-selected plan step."""

    run_state: RunState
    turn: Any
    plan_id: str | None = None
    plan_step_id: str | None = None


@dataclass(frozen=True)
class StepExecutionResult:
    """Result returned by the current thin ExecutorAgent wrapper."""

    answer: str
    run_state: RunState
    plan_id: str | None = None
    plan_step_id: str | None = None


class ExecutorAgent:
    """Wrap the existing Agent loop before the execution loop is migrated."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def execute_step(self, context: StepExecutionContext) -> StepExecutionResult:
        answer = self.agent._run_agent_loop(context.run_state, context.turn)
        return StepExecutionResult(
            answer=answer,
            run_state=context.run_state,
            plan_id=context.plan_id,
            plan_step_id=context.plan_step_id,
        )

