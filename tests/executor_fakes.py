from __future__ import annotations

from collections.abc import Iterable

from app.executor.models import (
    ExecutorContextContribution,
    ExecutorDecision,
    ExecutorFeedbackItem,
    ExecutorMemoryContribution,
    ExecutorModelInput,
    ExecutorResult,
)
from app.runtime.models import RuntimeRequest
from app.tools.models import ConfirmedAction, ToolCall, ToolDefinition
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

    def load(
        self, request: RuntimeRequest
    ) -> tuple[ExecutorContextContribution, ...]:
        self.requests.append(request)
        return self._contributions


class FakeExecutorMemoryProvider:
    def __init__(
        self, contributions: tuple[ExecutorMemoryContribution, ...]
    ) -> None:
        self._contributions = contributions
        self.requests: list[RuntimeRequest] = []

    def load(
        self, request: RuntimeRequest
    ) -> tuple[ExecutorMemoryContribution, ...]:
        self.requests.append(request)
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

    def on_stop(self, result: ExecutorResult) -> None:
        self.results.append(result)


class RecordingExecutorFeedbackSink:
    def __init__(self) -> None:
        self.items: list[ExecutorFeedbackItem] = []

    def record(self, step_or_result: ExecutorFeedbackItem) -> None:
        self.items.append(step_or_result)
