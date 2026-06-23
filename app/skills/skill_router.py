import re
from dataclasses import dataclass
from typing import Pattern

from app.skills.skill_loader import SkillMetadata


MAX_SELECTED_SKILLS = 4


@dataclass(frozen=True)
class RoutingRule:
    """Deterministic phrase rule contributing to one Skill score."""

    pattern: Pattern[str]
    reason: str
    weight: int = 1


@dataclass(frozen=True)
class RoutingDecision:
    """Selected Skills with scores and human-readable match reasons."""

    selected: tuple[str, ...]
    scores: dict[str, int]
    reasons: dict[str, tuple[str, ...]]
    fallback_used: bool


def _rule(pattern: str, reason: str, weight: int = 1) -> RoutingRule:
    return RoutingRule(re.compile(pattern, re.IGNORECASE), reason, weight)


ROUTING_RULES: dict[str, tuple[RoutingRule, ...]] = {
    "todo": (
        _rule(r"待办|任务|提醒|截止|优先级|完成.*(?:事项|任务)|删除.*(?:事项|任务)", "任务管理意图", 2),
        _rule(r"安排.*(?:今天|明天|一天)|今天.*计划|日计划|plan\s+(?:my\s+)?day", "日程规划意图", 2),
        _rule(r"\b(?:todo|task|remind|deadline)\b", "Todo 关键词"),
    ),
    "wellbeing": (
        _rule(r"睡眠|睡了|没睡|失眠|心情|情绪|能量|精力|疲惫|累了|压力|状态", "身心状态信号", 2),
        _rule(r"\b(?:sleep|mood|energy|tired|stress|wellbeing)\b", "Wellbeing 关键词"),
    ),
    "finance": (
        _rule(r"花了|消费|开销|支出|账单|记账|多少钱|超支|余额", "消费或金额意图", 2),
        _rule(r"预算(?:紧|不足|剩|设|设置|检查|超|为|是)|餐饮预算|交通预算|月预算|周预算", "预算管理意图", 2),
        _rule(r"\b(?:expense|spending|budget|cost|finance)\b", "Finance 关键词"),
    ),
    "activity": (
        _rule(r"推荐.*(?:活动|休息|运动)|恢复活动|免费活动|散步|冥想|拉伸|休息一下", "活动推荐意图", 2),
        _rule(r"(?:不花钱|低成本).*(?:活动|放松|恢复)|(?:活动|放松|恢复).*(?:不花钱|低成本)", "活动成本约束"),
        _rule(r"\b(?:activity|break|exercise|recover|relax)\b", "Activity 关键词"),
    ),
}


def route_skills(
    user_input: str,
    available_skills: dict[str, SkillMetadata],
    max_selected: int = MAX_SELECTED_SKILLS,
) -> RoutingDecision:
    """Select Skills using deterministic domain phrase scoring."""
    scores: dict[str, int] = {}
    reasons: dict[str, tuple[str, ...]] = {}

    for skill_name, rules in ROUTING_RULES.items():
        if skill_name not in available_skills:
            continue
        matched = [rule for rule in rules if rule.pattern.search(user_input)]
        if not matched:
            continue
        scores[skill_name] = sum(rule.weight for rule in matched)
        reasons[skill_name] = tuple(rule.reason for rule in matched)

    ranked = sorted(scores, key=lambda name: (-scores[name], name))
    selected = tuple(ranked[:max_selected])
    return RoutingDecision(
        selected=selected,
        scores=scores,
        reasons={name: reasons[name] for name in selected},
        fallback_used=not selected,
    )
