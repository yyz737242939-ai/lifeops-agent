"""LangGraph wiring for the request-local runtime orchestration flow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.intent.service import IntentService
from app.observability.logger import TraceSink
from app.orchestration.nodes import (
    classify_intent,
    decide_policy,
    deny,
    finalize,
    require_confirmation,
    stub_execute,
)
from app.orchestration.state import GraphRoute, GraphState, create_graph_state
from app.policy.service import PolicyService
from app.runtime.models import RuntimeRequest, RuntimeResult


@dataclass(frozen=True)
class OrchestrationContext:
    """Request-local dependencies that must not become graph state."""

    trace: TraceSink | None = None


def build_runtime_graph(
    intent_service: IntentService,
    policy_service: PolicyService,
) -> CompiledStateGraph:
    """Build and compile the stage-4 runtime orchestration graph."""

    graph = StateGraph(GraphState, context_schema=OrchestrationContext)
    graph.add_node(
        "classify_intent",
        _with_runtime_trace(
            partial(classify_intent, intent_service=intent_service),
        ),
    )
    graph.add_node(
        "decide_policy",
        _with_runtime_trace(
            partial(decide_policy, policy_service=policy_service),
        ),
    )
    graph.add_node("stub_execute", stub_execute)
    graph.add_node("requires_confirmation", require_confirmation)
    graph.add_node("deny", deny)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _route_after_intent,
        {
            "continue": "decide_policy",
            "error": END,
        },
    )
    graph.add_conditional_edges(
        "decide_policy",
        _route_after_policy_or_error,
        {
            GraphRoute.ALLOW: "stub_execute",
            GraphRoute.REQUIRES_CONFIRMATION: "requires_confirmation",
            GraphRoute.DENY: "deny",
            "error": END,
        },
    )
    graph.add_edge("stub_execute", "finalize")
    graph.add_edge("requires_confirmation", "finalize")
    graph.add_edge("deny", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


class RuntimeOrchestrator:
    """Invoke the compiled graph while keeping RuntimeService as the future entrypoint."""

    def __init__(
        self,
        intent_service: IntentService | None = None,
        policy_service: PolicyService | None = None,
    ) -> None:
        self._intent_service = intent_service or IntentService()
        self._policy_service = policy_service or PolicyService()
        self._graph = build_runtime_graph(
            self._intent_service,
            self._policy_service,
        )

    def invoke(
        self,
        request: RuntimeRequest,
        trace: TraceSink | None = None,
    ) -> GraphState:
        """Run the compiled graph and return its request-local final state."""

        final_state = cast(
            GraphState,
            self._graph.invoke(
                create_graph_state(request),
                context=OrchestrationContext(trace=trace),
            ),
        )
        if final_state["result"] is None:
            raise RuntimeError("runtime graph completed without a result.")
        return final_state

    def handle(
        self,
        request: RuntimeRequest,
        trace: TraceSink | None = None,
    ) -> RuntimeResult:
        """Run the compiled graph and return its structured runtime result."""

        final_state = self.invoke(request, trace=trace)
        result = final_state["result"]
        if result is None:
            raise RuntimeError("runtime graph completed without a result.")
        return result


def _route_after_intent(state: GraphState) -> Literal["continue", "error"]:
    if state["error_code"] is not None:
        return "error"
    return "continue"


def _route_after_policy_or_error(
    state: GraphState,
) -> GraphRoute | Literal["error"]:
    if state["error_code"] is not None:
        return "error"
    route = state["route"]
    if route is None:
        raise ValueError("route must be available after policy evaluation.")
    return route


def _with_runtime_trace(
    action: Callable[..., GraphState],
) -> Callable[[GraphState, Runtime[OrchestrationContext]], GraphState]:
    """Bind the request-local sink while keeping it outside GraphState."""

    def invoke_node(
        state: GraphState,
        runtime: Runtime[OrchestrationContext],
    ) -> GraphState:
        trace = runtime.context.trace if runtime.context is not None else None
        return action(state, trace=trace)

    return invoke_node
