import re
from dataclasses import dataclass
from typing import Pattern


CONTEXT_REF_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"引用|ref[_\s-]?id|context\s+ref", re.IGNORECASE),
    re.compile(r"完整(?:结果|明细)|展开.*(?:结果|明细)", re.IGNORECASE),
    re.compile(r"full\s+(?:result|details)|expand.*(?:result|details)", re.IGNORECASE),
)

CONTINUATION_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"继续|接着|刚才(?:那个|的)|上一个", re.IGNORECASE),
    re.compile(r"第[一二三四五六七八九十\d]+(?:个|项|条|笔)", re.IGNORECASE),
    re.compile(r"(?:那|这)(?:个|项|条|笔)|(?:完成|删除|修改)它|改成", re.IGNORECASE),
    re.compile(
        r"\b(?:continue|keep\s+going|the\s+(?:first|second|third)|that\s+one|previous\s+one)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class SkillStateDecision:
    previous_active_skills: tuple[str, ...]
    directly_selected: tuple[str, ...]
    inherited_skills: tuple[str, ...]
    loaded_skills: tuple[str, ...]
    next_active_skills: tuple[str, ...]
    inheritance_used: bool
    state_cleared: bool
    resolution: str


def _unique(items: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _matches_any(user_input: str, patterns: tuple[Pattern[str], ...]) -> bool:
    return any(pattern.search(user_input) for pattern in patterns)


def resolve_skill_state(
    user_input: str,
    directly_selected: tuple[str, ...] | list[str],
    previous_active_skills: tuple[str, ...] | list[str],
) -> SkillStateDecision:
    direct = _unique(directly_selected)
    previous = _unique(previous_active_skills)

    # Explicit domain evidence always replaces inherited state.
    if direct:
        return SkillStateDecision(
            previous_active_skills=previous,
            directly_selected=direct,
            inherited_skills=(),
            loaded_skills=direct,
            next_active_skills=direct,
            inheritance_used=False,
            state_cleared=False,
            resolution="direct_selection",
        )

    # A Ref-only turn needs the common read_context_ref capability, not every
    # tool from the previous domain. Preserve the topic for a possible next turn.
    if _matches_any(user_input, CONTEXT_REF_PATTERNS):
        return SkillStateDecision(
            previous_active_skills=previous,
            directly_selected=(),
            inherited_skills=(),
            loaded_skills=(),
            next_active_skills=previous,
            inheritance_used=False,
            state_cleared=False,
            resolution="context_ref_only",
        )

    if _matches_any(user_input, CONTINUATION_PATTERNS):
        inherited = previous
        return SkillStateDecision(
            previous_active_skills=previous,
            directly_selected=(),
            inherited_skills=inherited,
            loaded_skills=inherited,
            next_active_skills=inherited,
            inheritance_used=bool(inherited),
            state_cleared=False,
            resolution=(
                "ambiguous_followup_inherited"
                if inherited
                else "followup_without_active_skill"
            ),
        )

    return SkillStateDecision(
        previous_active_skills=previous,
        directly_selected=(),
        inherited_skills=(),
        loaded_skills=(),
        next_active_skills=(),
        inheritance_used=False,
        state_cleared=bool(previous),
        resolution="no_domain_or_continuation",
    )
