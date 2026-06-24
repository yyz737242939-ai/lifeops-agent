import re


WRITE_TOOL_NAMES = frozenset(
    {
        "add_todo",
        "complete_todo",
        "update_todo",
        "delete_todo",
        "record_daily_state",
        "record_expense",
        "set_budget",
    }
)


def authorized_write_tools(user_input: str) -> frozenset[str]:
    """Return only writes explicitly authorized by the current user message."""
    text = user_input.strip().lower()
    authorized: set[str] = set()

    if re.search(r"提醒我|(?:添加|新增|创建|加入|加到).*待办|再加一个|add (?:a )?todo", text):
        authorized.add("add_todo")
    if re.search(r"(?:完成|标记为已?完成|勾选完成).*(?:待办|任务|[“\"'])|^(?:完成|标记为已?完成|勾选完成)", text):
        authorized.add("complete_todo")
    if re.search(r"(?:修改|更新|调整|改成|改到|重命名).*(?:待办|任务|日期|优先级|[“\"'])|^把.*(?:改成|改到)", text):
        authorized.add("update_todo")
    if re.search(r"删除|移除|清空|delete", text):
        authorized.add("delete_todo")

    write_cue = _has_explicit_write_cue(text)
    wellbeing_cue = bool(re.search(r"睡眠|睡了|心情|情绪|能量|精力|状态|wellbeing", text))
    if write_cue and wellbeing_cue:
        authorized.add("record_daily_state")

    finance_write_cue = _has_explicit_write_cue(text)
    finance_cue = bool(re.search(r"元|块|金额|消费|支出|花了|早餐|午饭|晚饭|咖啡|打车|expense", text))
    if finance_write_cue and finance_cue:
        authorized.add("record_expense")

    if re.search(r"预算", text) and re.search(r"设置|设为|设成|定为|修改|更新|调整|set", text):
        authorized.add("set_budget")

    if requires_bulk_delete_confirmation(text):
        authorized.discard("delete_todo")
    return frozenset(authorized)


def _has_explicit_write_cue(text: str) -> bool:
    """Prefer false negatives over persisting descriptive or historical context."""
    return bool(
        re.search(
            r"^(?:请|帮我|给我|替我)?\s*(?:记录|保存|录入|更新|修改|record|save|update)"
            r"|(?:请|帮我|给我|替我)\s*(?:记录|保存|录入|更新|修改)"
            r"|记一下|记下|记一笔|记账|记到|重复记录"
            r"|把.{0,40}(?:更新为|修改为)",
            text,
        )
    )


def requires_bulk_delete_confirmation(user_input: str) -> bool:
    """Require explicit confirmation before destructive bulk deletion."""
    text = user_input.strip().lower()
    destructive = bool(re.search(r"删除|移除|清空|delete", text))
    bulk = bool(re.search(r"所有|全部|全都|整个|清空|all|everything", text))
    confirmed = bool(re.search(r"确认|确定|我确认|继续删除|是的.*删除|confirm", text))
    return destructive and bulk and not confirmed


def has_write_success_claim(answer: str) -> bool:
    """Detect user-facing claims that persisted data was successfully changed."""
    patterns = (
        r"已(?:成功)?(?:为你)?(?:添加|记录|保存|更新|修改|删除|设置)",
        r"(?:添加|记录|保存|更新|修改|删除|设置)(?:成功|完成)",
        r"(?:待办|任务).{0,16}(?:已完成|标记为完成)",
        r"(?:successfully\s+)?(?:added|recorded|saved|updated|deleted|set)\b",
    )
    lowered = answer.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns)
