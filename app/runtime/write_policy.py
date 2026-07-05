import re


WRITE_TOOL_NAMES = frozenset(
    {
        "add_todo",
        "complete_todo",
        "update_todo",
        "delete_todo",
        "record_daily_state",
        "record_expense",
        "save_memory",
        "delete_memory",
        "create_task",
        "update_task_status",
        "add_task_step",
        "update_task_step",
        "set_current_task_step",
        "add_task_note",
        "add_task_blocker",
        "resolve_task_blocker",
        "set_budget",
    }
)


def authorized_write_tools(user_input: str) -> frozenset[str]:
    """Return only writes explicitly authorized by the current user message."""
    text = user_input.strip().lower()
    authorized: set[str] = set()

    if re.search(
        r"提醒我"
        r"|(?:添加|新增|创建|加入|加到).*(?:待办|todo)"
        r"|再(?:添加|新增|创建|加)一个"
        r"|add (?:a )?todo",
        text,
    ):
        authorized.add("add_todo")
    if re.search(
        r"(?:完成|标记为已?完成|标记完成|勾选完成).*(?:待办|任务|[“\"'])"
        r"|^把.*(?:标记为已?完成|标记完成)"
        r"|^(?:完成|标记为已?完成|标记完成|勾选完成)",
        text,
    ):
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

    memory_delete_cue = _has_memory_delete_cue(text)
    if memory_delete_cue:
        authorized.add("delete_memory")

    if _has_memory_save_cue(text) and not memory_delete_cue:
        authorized.add("save_memory")

    authorized.update(_authorized_task_write_tools(text))

    if memory_delete_cue and not re.search(r"待办|任务|todo", text):
        authorized.discard("delete_todo")

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


def _has_memory_save_cue(text: str) -> bool:
    return bool(
        re.search(
            r"长期记住|请记住|帮我记住|给我记住|记住"
            r"|以后默认|之后默认|以后都"
            r"|保存.{0,20}(?:偏好|事实|目标|约束|记忆)"
            r"|把.{0,30}(?:偏好|事实|目标|约束|习惯).{0,20}(?:保存|记下来|记住)"
            r"|save (?:this )?(?:memory|preference|fact|goal|constraint)",
            text,
        )
    )


def _has_memory_delete_cue(text: str) -> bool:
    return bool(
        re.search(
            r"忘掉|别再记|不要再记|不用再记"
            r"|删除.{0,20}(?:记忆|memory)"
            r"|移除.{0,20}(?:记忆|memory)"
            r"|delete .{0,20}memory|forget",
            text,
        )
    )


def _authorized_task_write_tools(text: str) -> set[str]:
    authorized: set[str] = set()
    task_cue = bool(re.search(r"task state|长期任务|任务状态|任务", text))

    if re.search(
        r"(?:创建|新增|保存|记录).{0,20}(?:长期任务|任务状态|task state)"
        r"|(?:创建|新增).{0,8}任务"
        r"|(?:帮我|请|把).{0,40}(?:创建|保存|记录).{0,20}(?:任务|task)"
        r"|(?:创建|新增).{0,20}task\b"
        r"|save .{0,30}as (?:a )?task",
        text,
    ):
        authorized.add("create_task")

    if not task_cue:
        return authorized

    if re.search(
        r"^(?:请|帮我|给我|替我)?\s*(?:暂停|恢复|取消).{0,12}任务"
        r"|^(?:请|帮我|给我|替我)?\s*完成.{0,12}任务"
        r"|(?:把|将).{0,30}任务.{0,20}(?:标记为已?完成|标记完成|标记为blocked|标记为阻塞|更新为|修改为|设为)"
        r"|(?:标记为已?完成|标记完成|更新状态|修改状态).{0,20}任务"
        r"|(?:pause|resume|complete|cancel|mark|update).{0,20}task",
        text,
    ):
        authorized.add("update_task_status")

    if re.search(
        r"(?:添加|新增|加入|补充).{0,20}(?:步骤|step)"
        r"|(?:add|create).{0,20}step",
        text,
    ):
        authorized.add("add_task_step")

    if re.search(
        r"(?:更新|修改|完成|跳过|标记).{0,20}(?:步骤|step)"
        r"|(?:update|complete|skip|mark).{0,20}step",
        text,
    ):
        authorized.add("update_task_step")

    if re.search(
        r"(?:当前|现在|正在).{0,12}(?:步骤|step)"
        r"|set .{0,20}current .{0,10}step",
        text,
    ):
        authorized.add("set_current_task_step")

    if re.search(
        r"(?:记录|添加|新增|保存).{0,20}(?:进展|备注|note)"
        r"|(?:add|save|record).{0,20}(?:note|progress)",
        text,
    ):
        authorized.add("add_task_note")

    if re.search(
        r"(?:卡住|阻塞|blocked|blocker|block).{0,30}(?:原因|因为|是|：|:)?",
        text,
    ):
        authorized.add("add_task_blocker")

    if re.search(
        r"(?:解决|解除|移除|关闭).{0,20}(?:阻塞|blocker|blocked)"
        r"|resolve .{0,20}blocker",
        text,
    ):
        authorized.add("resolve_task_blocker")

    return authorized


def has_write_success_claim(answer: str) -> bool:
    """Detect user-facing claims that persisted data was successfully changed."""
    lowered = answer.lower()
    negative_or_explanatory = (
        r"(?:不能|无法|没有|未).{0,20}(?:保存|修改|写入|记录|删除|设置)",
        r"(?:保存|修改|写入|记录|删除|设置).{0,12}(?:不能|无法|不算|不等于)",
        r"(?:才|才能).{0,12}(?:证明|确认).{0,20}(?:保存|修改|写入|记录|删除|设置)",
        r"write action.{0,40}(?:证明|confirm|prove)",
    )
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in negative_or_explanatory):
        return False
    patterns = (
        r"已(?:成功)?(?:为你)?(?:创建|添加|记录|保存|更新|修改|删除|设置)",
        r"(?:创建|添加|记录|保存|更新|修改|删除|设置)(?:成功|完成)",
        r"(?:待办|任务).{0,16}(?:已完成|标记为完成)",
        r"(?:successfully\s+)?(?:added|recorded|saved|updated|deleted|set)\b",
    )
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns)
