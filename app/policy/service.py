"""Policy evaluation service."""

from __future__ import annotations

from app.common.text import contains_any, normalize_search_text
from app.intent.models import IntentDecision, IntentType
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest


class PolicyService:
    """Evaluates what the runtime is allowed to do for one request."""

    def evaluate(self, request: RuntimeRequest, intent: IntentDecision) -> PolicyDecision:
        """Produce a request-local policy decision from request text and intent."""

        if intent.intent_type == IntentType.WRITE_REQUEST:
            if _identifies_supported_write_target(request.user_input):
                return PolicyDecision(
                    action=PolicyAction.ALLOW,
                    allowed_effects=["write"],
                    reason="Explicit write request identifies a supported target.",
                )
            return PolicyDecision(
                action=PolicyAction.REQUIRES_CONFIRMATION,
                requires_confirmation=True,
                reason="Write request does not identify a supported target.",
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
                allowed_effects=["read", "external_read"],
                reason="Read intent is allowed without write authorization.",
            )
        if intent.intent_type in {IntentType.CHAT, IntentType.PLAN_REQUEST}:
            return PolicyDecision(
                action=PolicyAction.ALLOW,
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


def _identifies_supported_write_target(user_input: str) -> bool:
    text = normalize_search_text(user_input)
    return contains_any(
        text,
        (
            "任务",
            "待办",
            "todo",
            "task",
            "记忆",
            "memory",
            "健康记录",
            "状态记录",
            "wellbeing",
            "研究",
            "笔记",
            "简报",
            "source",
            "brief",
            "note",
            "旅行",
            "行程",
            "trip",
            "itinerary",
        ),
    )
