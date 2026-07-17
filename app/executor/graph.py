"""Compiled bounded action-observation graph owned by the Executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.executor.adapters import NoOpExecutorFeedbackSink
from app.executor.models import (
    ExecutionLimits,
    ExecutorContextContribution,
    ExecutorMemoryContribution,
    ExecutorModelInput,
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    PlanStepExecutionInput,
    ToolActionDecision,
    ToolObservation,
)
from app.executor.errors import InvalidExecutorModelActionError
from app.executor.ports import ExecutorFeedbackSink, ExecutorModelClient
from app.executor.routes import route_after_decision, route_after_tool
from app.executor.state import ExecutorState
from app.tools.models import ToolCall, ToolCallStatus, ToolResult
from app.observability.logger import LlmInteractionSink, TraceSink


class ExecutorToolExecutor(Protocol):
    """Step-4 test seam replaced by ToolRuntime/Gateway wiring in step 5."""

    def execute(self, call: ToolCall) -> ToolResult:
        ...


@dataclass(frozen=True)
class ExecutorGraphContext:
    """Invocation-local graph inputs and dependencies kept outside state."""

    model_client: ExecutorModelClient
    tool_executor: ExecutorToolExecutor
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)
    context_contributions: tuple[ExecutorContextContribution, ...] = field(
        default_factory=tuple
    )
    memory_contributions: tuple[ExecutorMemoryContribution, ...] = field(
        default_factory=tuple
    )
    feedback_sink: ExecutorFeedbackSink = field(
        default_factory=NoOpExecutorFeedbackSink
    )
    trace: TraceSink | None = None
    llm_log: LlmInteractionSink | None = None
    plan_step_input: PlanStepExecutionInput | None = None


def build_executor_graph() -> CompiledStateGraph:
    """Compile the pure Executor cycle without a checkpointer."""

    graph = StateGraph(ExecutorState, context_schema=ExecutorGraphContext)
    graph.add_node("decide", _decide)
    graph.add_node("execute_tool", _execute_tool)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges(
        "decide",
        route_after_decision,
        {"tool": "execute_tool", "end": END},
    )
    graph.add_conditional_edges(
        "execute_tool",
        route_after_tool,
        {"continue": "decide", "end": END},
    )
    return graph.compile()


def invoke_executor_graph(
    graph: CompiledStateGraph,
    state: ExecutorState,
    context: ExecutorGraphContext,
) -> ExecutorState:
    """Invoke with enough framework recursion headroom for max_steps=16."""

    recursion_limit = context.limits.max_steps * 2 + 4
    return cast(
        ExecutorState,
        graph.invoke(
            state,
            context=context,
            config={"recursion_limit": recursion_limit},
        ),
    )


def _decide(
    state: ExecutorState,
    runtime: Runtime[ExecutorGraphContext],
) -> ExecutorState:
    context = runtime.context
    if context is None:
        return _finish_failure(
            state,
            ExecutorStopReason.EXECUTOR_INTERNAL_FAILED,
            "executor_context_missing",
        )
    if state["step_count"] >= context.limits.max_steps:
        return _finish(
            state,
            status=ExecutorStatus.STOPPED,
            stop_reason=ExecutorStopReason.LIMIT_REACHED,
        )

    step_count = state["step_count"] + 1
    blocked_tool_names = _non_retryable_failed_tools(state)
    exhausted_tool_names = _exhausted_tool_names(state)
    tool_catalog = tuple(
        item
        for item in state["tool_catalog"]
        if item.get("name") not in blocked_tool_names
        and item.get("name") not in exhausted_tool_names
    )
    model_input = ExecutorModelInput(
        request=state["request"],
        prompt_contributions=state["prompt_contributions"],
        context_contributions=context.context_contributions,
        memory_contributions=context.memory_contributions,
        tool_catalog=tool_catalog,
        observations=tuple(state["observations"]),
        step_index=step_count,
        plan_step=context.plan_step_input,
    )
    next_state = _updated(
        state,
        step_count=step_count,
        executor_path=[*state["executor_path"], "decide"],
    )
    try:
        if context.llm_log is None:
            decision = context.model_client.decide(model_input)
        else:
            decision = context.model_client.decide(
                model_input,
                llm_log=context.llm_log,
            )
    except InvalidExecutorModelActionError as exc:
        return _finish_failure(
            next_state,
            ExecutorStopReason.INVALID_MODEL_ACTION,
            exc.code,
        )
    except Exception:
        return _finish_failure(
            next_state,
            ExecutorStopReason.MODEL_FAILED,
            "executor_model_failed",
        )
    if not isinstance(
        decision, (ToolActionDecision, FinalAnswerDecision, GoalNotAchievedDecision)
    ):
        return _finish_failure(
            next_state,
            ExecutorStopReason.INVALID_MODEL_ACTION,
            "executor_invalid_model_action",
        )
    next_state = _updated(next_state, current_decision=decision)
    if isinstance(decision, GoalNotAchievedDecision):
        if context.plan_step_input is None:
            return _finish_failure(
                next_state,
                ExecutorStopReason.INVALID_MODEL_ACTION,
                "executor_invalid_model_action",
            )
        _trace_action(context.trace, step_count, "goal_not_achieved")
        return _finish(
            next_state,
            status=ExecutorStatus.STOPPED,
            stop_reason=ExecutorStopReason.GOAL_NOT_ACHIEVED,
            error_code="plan_step_goal_not_achieved",
        )
    if isinstance(decision, FinalAnswerDecision):
        _trace_action(context.trace, step_count, "final_answer")
        return _finish(
            next_state,
            status=ExecutorStatus.COMPLETED,
            stop_reason=ExecutorStopReason.FINAL_ANSWER,
            final_message=decision.message,
        )
    if decision.call.tool_name in blocked_tool_names:
        return _finish_failure(
            next_state,
            ExecutorStopReason.INVALID_MODEL_ACTION,
            "executor_non_retryable_tool_reselected",
        )
    if decision.call.tool_name in exhausted_tool_names:
        return _finish_failure(
            next_state,
            ExecutorStopReason.INVALID_MODEL_ACTION,
            "executor_tool_call_limit_exceeded",
        )
    if decision.call.call_id in {
        observation.call_id for observation in state["observations"]
    }:
        return _finish_failure(
            next_state,
            ExecutorStopReason.INVALID_MODEL_ACTION,
            "executor_duplicate_call_id",
        )
    _trace_action(
        context.trace,
        step_count,
        "tool_action",
        call=decision.call,
    )
    return next_state


def _non_retryable_failed_tools(state: ExecutorState) -> frozenset[str]:
    return frozenset(
        observation.tool_name
        for observation in state["observations"]
        if (
            observation.status == ToolCallStatus.FAILED
            and observation.error is not None
            and not observation.error.retryable
        )
    )


def _exhausted_tool_names(state: ExecutorState) -> frozenset[str]:
    call_counts: dict[str, int] = {}
    for observation in state["observations"]:
        call_counts[observation.tool_name] = call_counts.get(observation.tool_name, 0) + 1
    return frozenset(
        str(item["name"])
        for item in state["tool_catalog"]
        if (
            isinstance(item.get("max_calls_per_run"), int)
            and not isinstance(item.get("max_calls_per_run"), bool)
            and call_counts.get(str(item.get("name")), 0)
            >= int(item["max_calls_per_run"])
        )
    )


def _execute_tool(
    state: ExecutorState,
    runtime: Runtime[ExecutorGraphContext],
) -> ExecutorState:
    context = runtime.context
    decision = state["current_decision"]
    if context is None or not isinstance(decision, ToolActionDecision):
        return _finish_failure(
            state,
            ExecutorStopReason.EXECUTOR_INTERNAL_FAILED,
            "executor_tool_route_invalid",
        )
    try:
        result = context.tool_executor.execute(decision.call)
    except Exception:
        return _finish_failure(
            state,
            ExecutorStopReason.EXECUTOR_INTERNAL_FAILED,
            "executor_tool_execution_failed",
        )
    if (
        not isinstance(result, ToolResult)
        or result.call_id != decision.call.call_id
        or result.tool_name != decision.call.tool_name
    ):
        return _finish_failure(
            state,
            ExecutorStopReason.EXECUTOR_INTERNAL_FAILED,
            "executor_tool_result_invalid",
        )

    observation = ToolObservation.from_tool_result(
        step_index=state["step_count"], result=result
    )
    _trace_observation(context.trace, observation)
    try:
        context.feedback_sink.record(
            observation, plan_step=context.plan_step_input
        )
    except Exception:
        _trace_hook_failure(context.trace, "feedback")
    next_state = _updated(
        state,
        observations=[*state["observations"], observation],
        current_decision=None,
        executor_path=[*state["executor_path"], "execute_tool"],
    )
    if result.status == ToolCallStatus.DENIED:
        return _finish(
            next_state,
            status=ExecutorStatus.STOPPED,
            stop_reason=ExecutorStopReason.SAFETY_DENIED,
            error_code=result.error.code if result.error else None,
            last_tool_result=result,
        )
    if result.status == ToolCallStatus.REQUIRES_CONFIRMATION:
        return _finish(
            next_state,
            status=ExecutorStatus.STOPPED,
            stop_reason=ExecutorStopReason.CONFIRMATION_REQUIRED,
            error_code=result.error.code if result.error else None,
            last_tool_result=result,
        )
    if state["step_count"] >= context.limits.max_steps:
        return _finish(
            next_state,
            status=ExecutorStatus.STOPPED,
            stop_reason=ExecutorStopReason.LIMIT_REACHED,
            last_tool_result=result,
        )
    return next_state


def _finish_failure(
    state: ExecutorState,
    stop_reason: ExecutorStopReason,
    error_code: str,
) -> ExecutorState:
    return _finish(
        state,
        status=ExecutorStatus.FAILED,
        stop_reason=stop_reason,
        error_code=error_code,
    )


def _finish(
    state: ExecutorState,
    *,
    status: ExecutorStatus,
    stop_reason: ExecutorStopReason,
    final_message: str | None = None,
    error_code: str | None = None,
    last_tool_result: ToolResult | None = None,
) -> ExecutorState:
    if last_tool_result is None and state["observations"]:
        last_tool_result = _tool_result_from(state["observations"][-1])
    result = ExecutorResult(
        run_id=state["request"].run_id,
        status=status,
        stop_reason=stop_reason,
        final_message=final_message,
        step_count=state["step_count"],
        observations=tuple(state["observations"]),
        last_tool_result=last_tool_result,
        error_code=error_code,
    )
    return _updated(state, result=result, error_code=error_code)


def _tool_result_from(observation: ToolObservation) -> ToolResult:
    return ToolResult(
        call_id=observation.call_id,
        tool_name=observation.tool_name,
        status=observation.status,
        output=observation.output,
        evidence=observation.evidence,
        error=observation.error,
    )


def _updated(state: ExecutorState, **changes: Any) -> ExecutorState:
    return cast(ExecutorState, {**state, **changes})


def _trace_action(
    trace: TraceSink | None,
    step_index: int,
    decision_type: str,
    *,
    call: ToolCall | None = None,
) -> None:
    payload: dict[str, object] = {
        "step_index": step_index,
        "decision_type": decision_type,
    }
    if call is not None:
        payload.update(call_id=call.call_id, tool_name=call.tool_name)
    if trace is not None:
        trace.append("executor.action.selected", payload)


def _trace_observation(
    trace: TraceSink | None, observation: ToolObservation
) -> None:
    if trace is None:
        return
    trace.append(
        "executor.observation.recorded",
        {
            "step_index": observation.step_index,
            "call_id": observation.call_id,
            "tool_name": observation.tool_name,
            "status": observation.status.value,
            "error_code": observation.error.code if observation.error else None,
            "retryable": observation.error.retryable if observation.error else False,
            "evidence_count": len(observation.evidence),
        },
    )


def _trace_hook_failure(trace: TraceSink | None, hook: str) -> None:
    if trace is not None:
        trace.append(
            "executor.hook.failed",
            {"hook": hook, "error_code": "executor_hook_failed"},
        )
