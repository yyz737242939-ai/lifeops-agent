"""Ordinary node functions used by the runtime orchestration graph."""

from __future__ import annotations

from typing import Any

from app.intent.models import IntentDecision
from app.intent.service import IntentService
from app.observability.logger import TraceSink
from app.orchestration.routes import route_after_policy
from app.orchestration.state import GraphState, append_graph_path
from app.policy.models import PolicyDecision
from app.policy.service import PolicyService
from app.runtime.models import RuntimeResult, RuntimeStatus
from app.skills.models import SkillSelection
from app.skills.service import SkillService


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
        updated["trace_summary"] = [_safe_error_summary(exc)]
        updated["result"] = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.ERROR,
            message="Intent classification failed.",
            error_code=updated["error_code"],
            trace_summary=updated["trace_summary"],
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
        updated["trace_summary"] = [_safe_error_summary(exc)]
        updated["result"] = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.ERROR,
            message="Policy evaluation failed.",
            intent=_intent_summary(intent),
            error_code=updated["error_code"],
            trace_summary=updated["trace_summary"],
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
    skill_service: SkillService | None,
    trace: TraceSink | None = None,
) -> GraphState:
    """Select and load request-local Skills without executing tools."""

    updated = _append_node(state, "prepare_skills")
    if skill_service is None:
        updated["skill_selection"] = SkillSelection(
            reason="Skill selection is not configured for this runtime."
        )
        updated["loaded_skill_ids"] = []
        updated["prompt_contributions"] = []
        return updated

    request = updated["request"]
    try:
        preparation = skill_service.prepare(request, trace=trace)
        updated["skill_selection"] = preparation.selection
        updated["loaded_skill_ids"] = list(preparation.loaded_skill_ids)
        updated["prompt_contributions"] = list(preparation.prompt_contributions)
    except Exception as exc:
        updated["error_code"] = "runtime.skill_failed"
        updated["error_stage"] = "skill"
        updated["trace_summary"] = [_safe_error_summary(exc)]
        updated["result"] = RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.ERROR,
            message="Skill preparation failed.",
            intent=_intent_summary(updated["intent"]),
            policy=_policy_summary(updated["policy"]),
            error_code=updated["error_code"],
            trace_summary=updated["trace_summary"],
        )
    return updated


def stub_execute(state: GraphState) -> GraphState:
    """Build the existing allow result without performing real execution."""

    return _build_policy_result(
        state,
        node_name="stub_execute",
        expected_status=RuntimeStatus.OK,
        message="Request passed intent and policy checks; execution is not implemented yet.",
    )


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
    updated["trace_summary"] = ["runtime.orchestration.stubbed"]
    updated["result"] = RuntimeResult(
        run_id=updated["request"].run_id,
        session_id=updated["request"].session_id,
        status=expected_status,
        message=message,
        intent=_intent_summary(intent),
        policy=_policy_summary(policy),
        trace_summary=updated["trace_summary"],
    )
    return updated


def _append_node(state: GraphState, node_name: str) -> GraphState:
    updated = state.copy()
    updated["graph_path"] = append_graph_path(state["graph_path"], node_name)
    return updated


def _intent_summary(intent: IntentDecision) -> dict[str, Any]:
    return {
        "intent_type": intent.intent_type.value,
        "confidence": intent.confidence,
        "needs_clarification": intent.needs_clarification,
        "write_candidate": intent.write_candidate,
        "classifier_results": [
            {
                "classifier_name": result.classifier_name,
                "status": result.status,
                "intent_type": result.intent_type.value,
                "confidence": result.confidence,
            }
            for result in intent.classifier_results
        ],
    }


def _policy_summary(policy: PolicyDecision) -> dict[str, Any]:
    return {
        "action": policy.action.value,
        "authorized_write_scopes": [
            scope.value for scope in policy.authorized_write_scopes
        ],
        "allowed_tools": policy.allowed_tools,
        "requires_confirmation": policy.requires_confirmation,
        "denied_reason": policy.denied_reason,
    }


def _safe_error_summary(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"
