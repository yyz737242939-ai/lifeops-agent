"""Ordinary node functions used by the runtime orchestration graph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.intent.models import IntentDecision
from app.intent.service import IntentService
from app.observability.logger import TraceSink
from app.orchestration.routes import route_after_policy
from app.orchestration.state import GraphState, append_graph_path
from app.policy.models import PolicyDecision
from app.policy.service import PolicyService
from app.runtime.models import RuntimeResult, RuntimeStatus
from app.skills.service import SkillService
from app.tools.authorization import resolve_allowed_tools
from app.tools.calling import ToolCallSelectionClient
from app.tools.models import ToolCallStatus, ToolResult
from app.tools.runtime import ToolRuntime


def classify_intent(
    state: GraphState,
    intent_service: IntentService,
    *,
    trace: TraceSink | None = None,
) -> GraphState:
    """Classify the request and preserve the stage-3 intent failure semantics."""

    updated = _append_node(state, "classify_intent")
    request = updated["request"]
    try:
        updated["intent"] = intent_service.classify(request)
    except Exception as exc:
        updated["error_code"] = "runtime.intent_failed"
        updated["error_stage"] = "intent"
        updated["result"] = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.ERROR,
            message="Intent classification failed.",
            error_code=updated["error_code"],
        )
        if trace is not None:
            trace.append(
                "intent.failed",
                {
                    "error_code": updated["error_code"],
                    "error_type": exc.__class__.__name__,
                },
            )
        return updated

    if trace is not None:
        trace.append("intent.classified", _intent_summary(updated["intent"]))
    return updated


def decide_policy(
    state: GraphState,
    policy_service: PolicyService,
    *,
    trace: TraceSink | None = None,
) -> GraphState:
    """Evaluate policy and preserve the stage-3 policy failure semantics."""

    intent = state["intent"]
    if intent is None:
        raise ValueError("intent must be available before policy evaluation.")

    updated = _append_node(state, "decide_policy")
    request = updated["request"]
    try:
        updated["policy"] = policy_service.evaluate(request, intent)
        updated["route"] = route_after_policy(updated)
    except Exception as exc:
        updated["error_code"] = "runtime.policy_failed"
        updated["error_stage"] = "policy"
        updated["result"] = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.ERROR,
            message="Policy evaluation failed.",
            error_code=updated["error_code"],
        )
        if trace is not None:
            trace.append(
                "policy.failed",
                {
                    "error_code": updated["error_code"],
                    "error_type": exc.__class__.__name__,
                },
            )
        return updated

    policy = updated["policy"]
    route = updated["route"]
    if policy is None or route is None:
        raise ValueError("policy and route must be available after policy evaluation.")
    if trace is not None:
        trace.append("policy.decided", _policy_summary(policy))
        trace.append("orchestration.route.selected", {"route": route.value})
    return updated


def prepare_skills(
    state: GraphState,
    *,
    skill_service: SkillService,
    trace: TraceSink | None = None,
) -> GraphState:
    """Select and load request-local Skills without executing tools."""

    updated = _append_node(state, "prepare_skills")
    request = updated["request"]
    try:
        preparation = skill_service.prepare(request, trace=trace)
        updated["skill_selection"] = preparation.selection
        updated["prompt_contributions"] = list(preparation.prompt_contributions)
    except Exception as exc:
        updated["error_code"] = "runtime.skill_failed"
        updated["error_stage"] = "skill"
        updated["result"] = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.ERROR,
            message="Skill preparation failed.",
            error_code=updated["error_code"],
        )
    return updated


def execute_tool(
    state: GraphState,
    *,
    execution_scope: ToolRuntime,
    selection_client: ToolCallSelectionClient,
    trace: TraceSink | None = None,
) -> GraphState:
    """Expose the authorized catalog, select one call, and execute it via Gateway."""

    updated = _append_node(state, "execute_tool")
    request = updated["request"]
    intent = updated["intent"]
    policy = updated["policy"]
    selection = updated["skill_selection"]
    if intent is None or policy is None or selection is None:
        raise ValueError("intent, policy, and Skill selection must precede execution.")

    try:
        tool_runtime = execution_scope
        allowed_tools = resolve_allowed_tools(
            selection.selected_skill_ids,
            policy,
            tool_runtime.registry,
        )
        catalog = tool_runtime.registry.model_catalog(allowed_tools.tool_names)
        if trace is not None:
            trace.append(
                "tool.catalog.resolved",
                {
                    "tool_names": list(allowed_tools.tool_names),
                    "tool_count": len(allowed_tools.tool_names),
                },
            )
        if not catalog:
            updated["result"] = RuntimeResult(
                run_id=request.run_id,
                session_id=request.session_id,
                status=RuntimeStatus.OK,
                message="No authorized Tool is available for this request.",
            )
            return updated

        call = selection_client.select(
            request,
            tuple(updated["prompt_contributions"]),
            catalog,
        )
        if call is None:
            updated["result"] = RuntimeResult(
                run_id=request.run_id,
                session_id=request.session_id,
                status=RuntimeStatus.OK,
                message="No Tool call was selected for this request.",
            )
            return updated

        result = tool_runtime.gateway.execute(call, allowed_tools, trace=trace)
        updated["result"] = _runtime_result_from_tool(
            request.run_id,
            request.session_id,
            result,
        )
    except Exception as exc:
        updated["error_code"] = getattr(exc, "code", None) or "runtime.tool_failed"
        updated["error_stage"] = "tool"
        updated["result"] = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.ERROR,
            message="Tool execution failed.",
            error_code=updated["error_code"],
        )
    return updated


def require_confirmation(state: GraphState) -> GraphState:
    """Build the existing confirmation result without invoking an interrupt."""

    return _build_policy_result(
        state,
        node_name="requires_confirmation",
        expected_status=RuntimeStatus.REQUIRES_CONFIRMATION,
        message="Request requires confirmation before execution.",
    )


def deny(state: GraphState) -> GraphState:
    """Build the existing policy-denied result."""

    return _build_policy_result(
        state,
        node_name="deny",
        expected_status=RuntimeStatus.UNSUPPORTED,
        message="Request is not allowed by policy.",
    )


def finalize(state: GraphState) -> GraphState:
    """Mark a successfully constructed result as finalized."""

    if state["result"] is None:
        raise ValueError("result must be available before finalization.")
    return _append_node(state, "finalize")


def _build_policy_result(
    state: GraphState,
    *,
    node_name: str,
    expected_status: RuntimeStatus,
    message: str,
) -> GraphState:
    intent = state["intent"]
    policy = state["policy"]
    if intent is None or policy is None:
        raise ValueError("intent and policy must be available before result construction.")

    updated = _append_node(state, node_name)
    updated["result"] = RuntimeResult(
        run_id=updated["request"].run_id,
        session_id=updated["request"].session_id,
        status=expected_status,
        message=message,
    )
    return updated


def _runtime_result_from_tool(
    run_id: str,
    session_id: str,
    result: ToolResult,
) -> RuntimeResult:
    status = {
        ToolCallStatus.SUCCEEDED: RuntimeStatus.OK,
        ToolCallStatus.REQUIRES_CONFIRMATION: RuntimeStatus.REQUIRES_CONFIRMATION,
        ToolCallStatus.DENIED: RuntimeStatus.UNSUPPORTED,
        ToolCallStatus.FAILED: RuntimeStatus.ERROR,
    }[result.status]
    error_code = result.error.code if result.error is not None else None
    return RuntimeResult(
        run_id=run_id,
        session_id=session_id,
        status=status,
        message=f"Tool call {result.status.value}: {result.tool_name}.",
        tool_result={
            "call_id": result.call_id,
            "tool_name": result.tool_name,
            "status": result.status.value,
            "output": result.output,
            "evidence": [
                {
                    "evidence_type": item.evidence_type,
                    "summary": item.summary,
                    "reference": item.reference,
                }
                for item in result.evidence
            ],
            "error": (
                {
                    "code": result.error.code,
                    "message": result.error.message,
                    "retryable": result.error.retryable,
                }
                if result.error is not None
                else None
            ),
        },
        error_code=error_code if status == RuntimeStatus.ERROR else None,
    )


def _append_node(state: GraphState, node_name: str) -> GraphState:
    updated = state.copy()
    updated["graph_path"] = append_graph_path(state["graph_path"], node_name)
    return updated


def _intent_summary(intent: IntentDecision) -> dict[str, Any]:
    return {
        "intent_type": intent.intent_type.value,
        "needs_clarification": intent.needs_clarification,
        "write_candidate": intent.write_candidate,
    }


def _policy_summary(policy: PolicyDecision) -> dict[str, Any]:
    return {
        "action": policy.action.value,
        "allowed_effects": policy.allowed_effects,
        "requires_confirmation": policy.requires_confirmation,
    }
