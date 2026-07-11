"""Policy evaluation service."""

from __future__ import annotations

from app.common.text import contains_any, normalize_search_text
from app.intent.models import IntentDecision, IntentType
from app.policy.models import PermissionScope, PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest


class PolicyService:
    """Evaluates what the runtime is allowed to do for one request."""

    def evaluate(self, request: RuntimeRequest, intent: IntentDecision) -> PolicyDecision:
        """Produce a request-local policy decision from request text and intent."""

        if intent.intent_type == IntentType.WRITE_REQUEST:
            scopes = _infer_write_scopes(request.user_input)
            if scopes:
                return PolicyDecision(
                    action=PolicyAction.ALLOW,
                    authorized_write_scopes=scopes,
                    reason="Explicit write request has a limited candidate scope.",
                )
            return PolicyDecision(
                action=PolicyAction.REQUIRES_CONFIRMATION,
                requires_confirmation=True,
                reason="Write request does not identify a supported write scope.",
            )
        if intent.write_candidate:
            return PolicyDecision(
                action=PolicyAction.REQUIRES_CONFIRMATION,
                requires_confirmation=True,
                reason="Possible write intent requires explicit confirmation.",
            )
        if intent.intent_type == IntentType.READ:
            return PolicyDecision(
                action=PolicyAction.ALLOW,
                authorized_write_scopes=[],
                reason="Read intent is allowed without write authorization.",
            )
        if intent.intent_type in {IntentType.CHAT, IntentType.PLAN_REQUEST}:
            return PolicyDecision(
                action=PolicyAction.ALLOW,
                authorized_write_scopes=[],
                reason="Non-write intent is allowed without write authorization.",
            )
        if intent.intent_type == IntentType.CLARIFICATION_NEEDED:
            return PolicyDecision(
                action=PolicyAction.REQUIRES_CONFIRMATION,
                requires_confirmation=True,
                reason="Intent needs clarification before execution.",
            )
        return PolicyDecision(
            action=PolicyAction.DENY,
            denied_reason="Unsupported or unknown intent is not allowed.",
            reason="Policy denies by default when intent is unsupported or unknown.",
        )


def _infer_write_scopes(user_input: str) -> list[PermissionScope]:
    text = normalize_search_text(user_input)
    scopes: list[PermissionScope] = []
    if contains_any(text, ("任务", "待办", "todo", "task")):
        scopes.append(PermissionScope.TASK_WRITE_CANDIDATE)
    if contains_any(text, ("记忆", "memory")):
        scopes.append(PermissionScope.MEMORY_WRITE_CANDIDATE)
    if contains_any(text, ("健康记录", "状态记录", "wellbeing")):
        scopes.append(PermissionScope.WELLBEING_WRITE_CANDIDATE)
    return scopes
