"""Safe default adapters for optional Executor input and observer ports."""

from __future__ import annotations

from app.executor.models import (
    ExecutorContextContribution,
    ExecutorFeedbackItem,
    ExecutorMemoryContribution,
    ExecutorResult,
    PlanStepExecutionInput,
)
from app.runtime.models import RuntimeRequest
from app.tools.models import ConfirmedAction, ToolCall, ToolDefinition


class EmptyExecutorContextProvider:
    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorContextContribution, ...]:
        return ()


class EmptyExecutorMemoryProvider:
    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorMemoryContribution, ...]:
        return ()


class NoOpActionConfirmationProvider:
    """Never claims that the user confirmed an action."""

    def confirm(
        self,
        run_id: str,
        call: ToolCall,
        tool_definition: ToolDefinition,
    ) -> ConfirmedAction | None:
        return None


class NoOpExecutorRecoveryHook:
    def on_stop(
        self,
        result: ExecutorResult,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        return None


class NoOpExecutorFeedbackSink:
    def record(
        self,
        step_or_result: ExecutorFeedbackItem,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        return None
