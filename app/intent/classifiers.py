"""Intent classifier interfaces and rule-based implementations."""

from __future__ import annotations

from typing import Protocol

from app.common.text import contains_any, normalize_search_text
from app.intent.models import ClassifierResult, IntentType
from app.runtime.models import RuntimeRequest


class IntentClassifier(Protocol):
    """Interface for components that produce one intent classification signal."""

    def classify(self, request: RuntimeRequest) -> ClassifierResult:
        """Classify one runtime request."""


class RuleBasedIntentClassifier:
    """Conservative intent classifier based on action and object phrases."""

    classifier_name = "rule_based"

    _WRITE_ACTIONS = (
        "加入",
        "添加",
        "新增",
        "记录",
        "记住",
        "保存",
        "创建",
        "更新",
        "修改",
        "归档",
        "删除",
        "设为",
        "标记",
        "add",
        "create",
        "save",
        "update",
        "archive",
        "delete",
        "remove",
        "record",
        "remember",
        "mark",
    )
    _WRITE_OBJECTS = (
        "任务",
        "待办",
        "todo",
        "memory",
        "记忆",
        "健康记录",
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
    )
    _PLAN_ACTIONS = (
        "帮我规划",
        "帮我计划",
        "规划一下",
        "计划一下",
        "安排一下",
        "制定",
        "plan for me",
        "help me plan",
    )
    _PLAN_OBJECTS = (
        "安排",
        "日程",
        "计划",
        "明天",
        "今天",
        "本周",
        "schedule",
        "day",
        "week",
    )
    _READ_ACTIONS = (
        "查看",
        "查询",
        "列出",
        "告诉我",
        "show",
        "list",
        "read",
        "search",
        "fetch",
        "搜索",
        "获取",
    )

    def classify(self, request: RuntimeRequest) -> ClassifierResult:
        """Classify one runtime request using conservative phrase combinations."""

        text = normalize_search_text(request.user_input)
        if not text:
            return self._result(
                status="low_confidence",
                intent_type=IntentType.CLARIFICATION_NEEDED,
                confidence=0.0,
                reason="User input is empty.",
            )
        if text in {"计划一下", "规划一下", "plan"}:
            return self._result(
                status="low_confidence",
                intent_type=IntentType.CLARIFICATION_NEEDED,
                confidence=0.35,
                reason="Planning keyword lacks enough action and object context.",
            )
        if contains_any(text, ("记住", "remember")):
            return self._result(
                status="matched",
                intent_type=IntentType.WRITE_REQUEST,
                confidence=0.9,
                reason="Input explicitly asks to remember durable information.",
            )
        if contains_any(text, self._WRITE_ACTIONS) and contains_any(
            text, self._WRITE_OBJECTS
        ):
            return self._result(
                status="matched",
                intent_type=IntentType.WRITE_REQUEST,
                confidence=0.9,
                reason="Input combines a write action with a writable object.",
            )
        if contains_any(text, self._PLAN_ACTIONS) and contains_any(
            text, self._PLAN_OBJECTS
        ):
            return self._result(
                status="matched",
                intent_type=IntentType.PLAN_REQUEST,
                confidence=0.85,
                reason="Input combines a planning action with a planning object.",
            )
        if contains_any(text, self._READ_ACTIONS):
            return self._result(
                status="matched",
                intent_type=IntentType.READ,
                confidence=0.75,
                reason="Input contains a read-oriented action.",
            )
        return self._result(
            status="matched",
            intent_type=IntentType.CHAT,
            confidence=0.6,
            reason="Input does not match write or planning request patterns.",
        )

    def _result(
        self,
        *,
        status: str,
        intent_type: IntentType,
        confidence: float,
        reason: str,
    ) -> ClassifierResult:
        return ClassifierResult(
            classifier_name=self.classifier_name,
            status=status,
            intent_type=intent_type,
            confidence=confidence,
            reason=reason,
        )


class LlmIntentClassifier:
    """Placeholder LLM classifier that does not call a model yet."""

    classifier_name = "llm"

    def classify(self, request: RuntimeRequest) -> ClassifierResult:
        """Return a safe unavailable signal until real structured LLM output exists."""

        return ClassifierResult(
            classifier_name=self.classifier_name,
            status="not_available",
            intent_type=IntentType.CLARIFICATION_NEEDED,
            confidence=0.0,
            reason="LLM intent classifier is not wired yet.",
        )
