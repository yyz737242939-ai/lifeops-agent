from __future__ import annotations

from collections.abc import Iterable

from app.executor.models import (
    ExecutorContextContribution,
    ExecutorDecision,
    ExecutorFeedbackItem,
    ExecutorMemoryContribution,
    ExecutorModelInput,
    ExecutorResult,
    PlanStepExecutionInput,
)
from app.runtime.models import RuntimeRequest
from app.tools.models import ConfirmedAction, ToolCall, ToolDefinition, ToolEffect
from app.tools.models import ToolResult


class FakeExecutorModelClient:
    def __init__(self, decisions: Iterable[ExecutorDecision]) -> None:
        self._decisions = list(decisions)
        self.inputs: list[ExecutorModelInput] = []

    def decide(self, model_input: ExecutorModelInput) -> ExecutorDecision:
        self.inputs.append(model_input)
        if not self._decisions:
            raise AssertionError("Fake Executor model has no decision remaining.")
        return self._decisions.pop(0)


class FakeExecutorToolGateway:
    def __init__(self, results: Iterable[ToolResult]) -> None:
        self._results = list(results)
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        if not self._results:
            raise AssertionError("Fake Tool Gateway has no result remaining.")
        return self._results.pop(0)


class FakeExecutorContextProvider:
    def __init__(
        self, contributions: tuple[ExecutorContextContribution, ...]
    ) -> None:
        self._contributions = contributions
        self.requests: list[RuntimeRequest] = []
        self.plan_steps: list[PlanStepExecutionInput | None] = []

    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorContextContribution, ...]:
        self.requests.append(request)
        self.plan_steps.append(plan_step)
        return self._contributions


class FakeExecutorMemoryProvider:
    def __init__(
        self, contributions: tuple[ExecutorMemoryContribution, ...]
    ) -> None:
        self._contributions = contributions
        self.requests: list[RuntimeRequest] = []
        self.plan_steps: list[PlanStepExecutionInput | None] = []

    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorMemoryContribution, ...]:
        self.requests.append(request)
        self.plan_steps.append(plan_step)
        return self._contributions


class FakeActionConfirmationProvider:
    def __init__(self, confirmed_action: ConfirmedAction | None) -> None:
        self._confirmed_action = confirmed_action
        self.requests: list[tuple[str, ToolCall, ToolDefinition]] = []

    def confirm(
        self,
        run_id: str,
        call: ToolCall,
        tool_definition: ToolDefinition,
    ) -> ConfirmedAction | None:
        self.requests.append((run_id, call, tool_definition))
        return self._confirmed_action


class RecordingExecutorRecoveryHook:
    def __init__(self) -> None:
        self.results: list[ExecutorResult] = []
        self.plan_steps: list[PlanStepExecutionInput | None] = []

    def on_stop(
        self,
        result: ExecutorResult,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        self.results.append(result)
        self.plan_steps.append(plan_step)


class RecordingExecutorFeedbackSink:
    def __init__(self) -> None:
        self.items: list[ExecutorFeedbackItem] = []
        self.plan_steps: list[PlanStepExecutionInput | None] = []
        self.run_ids: list[str | None] = []
        self.executor_invocation_ids: list[str | None] = []
        self.source_span_ids: list[str | None] = []
        self.tool_effects: list[ToolEffect | None] = []

    def record(
        self,
        step_or_result: ExecutorFeedbackItem,
        *,
        run_id: str | None = None,
        executor_invocation_id: str | None = None,
        source_span_id: str | None = None,
        tool_effect: ToolEffect | None = None,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        self.items.append(step_or_result)
        self.plan_steps.append(plan_step)
        self.run_ids.append(run_id)
        self.executor_invocation_ids.append(executor_invocation_id)
        self.source_span_ids.append(source_span_id)
        self.tool_effects.append(tool_effect)
