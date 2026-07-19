"""Safe default adapters for optional Executor input and observer ports."""

from __future__ import annotations

import inspect

from app.context.models import (
    ContextAssembly,
    ContextContributionKind,
)
from app.context.projection import project_context_contributions
from app.executor.models import (
    ExecutorContextContribution,
    ExecutorFeedbackItem,
    ExecutorMemoryContribution,
    ExecutorResult,
    PlanStepExecutionInput,
)
from app.runtime.models import RuntimeRequest
from app.tools.models import ConfirmedAction, ToolCall, ToolDefinition, ToolEffect


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


class AssemblyExecutorContextProvider:
    """Project conversation slots from one already-frozen ContextAssembly."""

    def __init__(self, assembly: ContextAssembly) -> None:
        if not isinstance(assembly, ContextAssembly):
            raise ValueError("assembly must be a ContextAssembly.")
        self.assembly_id = assembly.assembly_id
        self._session_id = assembly.session_id
        self._run_id = assembly.run_id
        self._contributions = tuple(
            ExecutorContextContribution(
                item.content,
                f"context-assembly://{assembly.assembly_id}/{item.kind.value}/{item.source}",
            )
            for item in project_context_contributions(assembly)
            if item.kind
            in {
                ContextContributionKind.CONVERSATION_SUMMARY,
                ContextContributionKind.CONVERSATION_TURN,
                ContextContributionKind.CURRENT_INPUT,
            }
        )

    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorContextContribution, ...]:
        _validate_assembly_request(request, self._session_id, self._run_id)
        return self._contributions


class AssemblyExecutorMemoryProvider:
    """Project Profile/Memory slots from the same frozen ContextAssembly."""

    def __init__(self, assembly: ContextAssembly) -> None:
        if not isinstance(assembly, ContextAssembly):
            raise ValueError("assembly must be a ContextAssembly.")
        self.assembly_id = assembly.assembly_id
        self._session_id = assembly.session_id
        self._run_id = assembly.run_id
        self._contributions = tuple(
            ExecutorMemoryContribution(
                item.content,
                f"context-assembly://{assembly.assembly_id}/{item.kind.value}/{item.source}",
            )
            for item in assembly.contributions
            if item.kind
            in {
                ContextContributionKind.PROFILE,
                ContextContributionKind.MEMORY,
            }
        )

    def load(
        self,
        request: RuntimeRequest,
        *,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> tuple[ExecutorMemoryContribution, ...]:
        _validate_assembly_request(request, self._session_id, self._run_id)
        return self._contributions


def _validate_assembly_request(
    request: RuntimeRequest, session_id: str, run_id: str
) -> None:
    if not isinstance(request, RuntimeRequest):
        raise ValueError("request must be a RuntimeRequest.")
    if request.session_id != session_id or request.run_id != run_id:
        raise ValueError("request identity must match the frozen ContextAssembly.")


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
        run_id: str | None = None,
        executor_invocation_id: str | None = None,
        source_span_id: str | None = None,
        tool_effect: ToolEffect | None = None,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        return None


def record_executor_feedback(
    sink,
    item: ExecutorFeedbackItem,
    **context,
) -> None:
    """Call new and legacy feedback sinks without retrying a failed sink body."""

    method = sink.record
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        method(item, **context)
        return
    accepts_extra = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    accepted_names = {parameter.name for parameter in parameters}
    selected = (
        context
        if accepts_extra
        else {name: value for name, value in context.items() if name in accepted_names}
    )
    method(item, **selected)
