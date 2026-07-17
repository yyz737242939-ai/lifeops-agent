"""Public reusable entrypoint for one bounded ReAct Executor invocation."""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph.state import CompiledStateGraph

from app.executor.adapters import (
    EmptyExecutorContextProvider,
    EmptyExecutorMemoryProvider,
    NoOpActionConfirmationProvider,
    NoOpExecutorFeedbackSink,
    NoOpExecutorRecoveryHook,
)
from app.executor.graph import (
    ExecutorGraphContext,
    build_executor_graph,
    invoke_executor_graph,
)
from app.executor.models import (
    ExecutionLimits,
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    PlanStepExecutionInput,
)
from app.executor.ports import (
    ExecutorContextProvider,
    ExecutorMemoryProvider,
    ExecutorModelClient,
    ActionConfirmationProvider,
    ExecutorFeedbackSink,
    ExecutorRecoveryHook,
)
from app.executor.state import create_executor_state
from app.observability.logger import LlmInteractionSink, TraceSink
from app.runtime.models import RuntimeRequest
from app.skills.models import PromptContribution
from app.tools.models import AllowedToolSet, ToolCall, ToolEffect, ToolResult
from app.tools.runtime import ToolRuntime


class ReactExecutor:
    """Load fixed inputs once and run the compiled action-observation cycle."""

    def __init__(
        self,
        model_client: ExecutorModelClient,
        *,
        limits: ExecutionLimits | None = None,
        context_provider: ExecutorContextProvider | None = None,
        memory_provider: ExecutorMemoryProvider | None = None,
        confirmation_provider: ActionConfirmationProvider | None = None,
        recovery_hook: ExecutorRecoveryHook | None = None,
        feedback_sink: ExecutorFeedbackSink | None = None,
        graph: CompiledStateGraph | None = None,
    ) -> None:
        self._model_client = model_client
        self._limits = limits or ExecutionLimits()
        self._context_provider = (
            context_provider or EmptyExecutorContextProvider()
        )
        self._memory_provider = memory_provider or EmptyExecutorMemoryProvider()
        self._confirmation_provider = (
            confirmation_provider or NoOpActionConfirmationProvider()
        )
        self._recovery_hook = recovery_hook or NoOpExecutorRecoveryHook()
        self._feedback_sink = feedback_sink or NoOpExecutorFeedbackSink()
        self._graph = graph or build_executor_graph()

    def execute(
        self,
        request: RuntimeRequest,
        prompt_contributions: tuple[PromptContribution, ...],
        allowed_tools: AllowedToolSet,
        execution_scope: ToolRuntime,
        trace: TraceSink | None = None,
        llm_log: LlmInteractionSink | None = None,
        *,
        context_provider: ExecutorContextProvider | None = None,
        memory_provider: ExecutorMemoryProvider | None = None,
    ) -> ExecutorResult:
        return self._execute(
            request,
            prompt_contributions,
            allowed_tools,
            execution_scope,
            trace,
            llm_log,
            plan_step_input=None,
            limits=self._limits,
            context_provider=context_provider,
            memory_provider=memory_provider,
        )

    def execute_step(
        self,
        request: RuntimeRequest,
        step_input: PlanStepExecutionInput,
        prompt_contributions: tuple[PromptContribution, ...],
        allowed_tools: AllowedToolSet,
        execution_scope: ToolRuntime,
        trace: TraceSink | None = None,
        llm_log: LlmInteractionSink | None = None,
        *,
        context_provider: ExecutorContextProvider | None = None,
        memory_provider: ExecutorMemoryProvider | None = None,
    ) -> ExecutorResult:
        if not isinstance(step_input, PlanStepExecutionInput):
            raise ValueError("step_input must be PlanStepExecutionInput.")
        effective_limits = ExecutionLimits(
            max_steps=min(self._limits.max_steps, step_input.max_steps)
        )
        return self._execute(
            request,
            prompt_contributions,
            allowed_tools,
            execution_scope,
            trace,
            llm_log,
            plan_step_input=step_input,
            limits=effective_limits,
            context_provider=context_provider,
            memory_provider=memory_provider,
        )

    def _execute(
        self,
        request: RuntimeRequest,
        prompt_contributions: tuple[PromptContribution, ...],
        allowed_tools: AllowedToolSet,
        execution_scope: ToolRuntime,
        trace: TraceSink | None,
        llm_log: LlmInteractionSink | None,
        *,
        plan_step_input: PlanStepExecutionInput | None,
        limits: ExecutionLimits,
        context_provider: ExecutorContextProvider | None,
        memory_provider: ExecutorMemoryProvider | None,
    ) -> ExecutorResult:
        if not isinstance(request, RuntimeRequest):
            raise ValueError("request must be a RuntimeRequest.")
        if not isinstance(allowed_tools, AllowedToolSet):
            raise ValueError("allowed_tools must be an AllowedToolSet.")
        if not isinstance(execution_scope, ToolRuntime):
            raise ValueError("execution_scope must be a ToolRuntime.")
        try:
            effective_context_provider = context_provider or self._context_provider
            effective_memory_provider = memory_provider or self._memory_provider
            context_contributions = effective_context_provider.load(
                request, plan_step=plan_step_input
            )
            memory_contributions = effective_memory_provider.load(
                request, plan_step=plan_step_input
            )
            catalog = execution_scope.registry.model_catalog(
                allowed_tools.tool_names
            )
        except Exception:
            return self._complete(
                ExecutorResult(
                run_id=request.run_id,
                status=ExecutorStatus.FAILED,
                stop_reason=ExecutorStopReason.INPUT_PROVIDER_FAILED,
                final_message=None,
                step_count=0,
                error_code="executor_input_provider_failed",
                ),
                trace,
                plan_step_input,
            )

        state = invoke_executor_graph(
            self._graph,
            create_executor_state(
                request,
                prompt_contributions=prompt_contributions,
                tool_catalog=catalog,
            ),
            ExecutorGraphContext(
                model_client=self._model_client,
                tool_executor=_GatewayToolExecutor(
                    execution_scope=execution_scope,
                    allowed_tools=allowed_tools,
                    run_id=request.run_id,
                    trace=trace,
                    confirmation_provider=self._confirmation_provider,
                ),
                limits=limits,
                context_contributions=context_contributions,
                memory_contributions=memory_contributions,
                feedback_sink=self._feedback_sink,
                trace=trace,
                llm_log=llm_log,
                plan_step_input=plan_step_input,
            ),
        )
        result = state["result"]
        if result is None:
            return self._complete(
                ExecutorResult(
                run_id=request.run_id,
                status=ExecutorStatus.FAILED,
                stop_reason=ExecutorStopReason.EXECUTOR_INTERNAL_FAILED,
                final_message=None,
                step_count=state["step_count"],
                observations=tuple(state["observations"]),
                error_code="executor_result_missing",
                ),
                trace,
                plan_step_input,
            )
        return self._complete(result, trace, plan_step_input)

    def _complete(
        self,
        result: ExecutorResult,
        trace: TraceSink | None,
        plan_step: PlanStepExecutionInput | None,
    ) -> ExecutorResult:
        try:
            self._feedback_sink.record(result, plan_step=plan_step)
        except Exception:
            _trace_hook_failure(trace, "feedback")
        try:
            self._recovery_hook.on_stop(result, plan_step=plan_step)
        except Exception:
            _trace_hook_failure(trace, "recovery")
        if trace is not None:
            payload: dict[str, object] = {
                "status": result.status.value,
                "stop_reason": result.stop_reason.value,
                "step_count": result.step_count,
            }
            if result.last_tool_result is not None:
                payload.update(
                    call_id=result.last_tool_result.call_id,
                    tool_name=result.last_tool_result.tool_name,
                )
            trace.append("executor.stopped", payload)
        return result


@dataclass(frozen=True)
class _GatewayToolExecutor:
    execution_scope: ToolRuntime
    allowed_tools: AllowedToolSet
    run_id: str
    trace: TraceSink | None
    confirmation_provider: ActionConfirmationProvider

    def execute(self, call: ToolCall) -> ToolResult:
        confirmation = None
        if (
            call.tool_name in self.allowed_tools.tool_names
            and self.execution_scope.registry.contains(call.tool_name)
        ):
            definition = self.execution_scope.registry.get(call.tool_name)
            if definition.effect == ToolEffect.WRITE:
                confirmation = self.confirmation_provider.confirm(
                    self.run_id,
                    call,
                    definition,
                )
        return self.execution_scope.gateway.execute(
            call,
            self.allowed_tools,
            confirmation=confirmation,
            run_id=self.run_id,
            trace=self.trace,
        )


def _trace_hook_failure(trace: TraceSink | None, hook: str) -> None:
    if trace is not None:
        trace.append(
            "executor.hook.failed",
            {"hook": hook, "error_code": "executor_hook_failed"},
        )
