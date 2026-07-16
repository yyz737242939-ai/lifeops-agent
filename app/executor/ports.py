"""Narrow ports used by the LifeOps-owned Executor."""

from __future__ import annotations

from typing import Protocol

from app.executor.models import (
    ExecutorContextContribution,
    ExecutorDecision,
    ExecutorFeedbackItem,
    ExecutorMemoryContribution,
    ExecutorModelInput,
    ExecutorResult,
    PlanStepExecutionInput,
)
from app.observability.logger import LlmInteractionSink
from app.runtime.models import RuntimeRequest
from app.tools.models import ConfirmedAction, ToolCall, ToolDefinition


class ExecutorModelClient(Protocol):
    def decide(
        self,
        model_input: ExecutorModelInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> ExecutorDecision:
        ...


class ExecutorContextProvider(Protocol):
    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorContextContribution, ...]:
        ...


class ExecutorMemoryProvider(Protocol):
    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorMemoryContribution, ...]:
        ...


class ActionConfirmationProvider(Protocol):
    def confirm(
        self,
        run_id: str,
        call: ToolCall,
        tool_definition: ToolDefinition,
    ) -> ConfirmedAction | None:
        ...


class ExecutorRecoveryHook(Protocol):
    def on_stop(
        self,
        result: ExecutorResult,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        ...


class ExecutorFeedbackSink(Protocol):
    def record(
        self,
        step_or_result: ExecutorFeedbackItem,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        ...
