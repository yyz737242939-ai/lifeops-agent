import re
from dataclasses import dataclass
from enum import StrEnum

from app.runtime.interaction_state import PendingConfirmation, RiskLevel


class PendingReplyIntent(StrEnum):
    """Deterministic interpretation of a user reply to pending safety state."""

    CONFIRM = "confirm"
    CANCEL = "cancel"
    MODIFY = "modify"
    UNRELATED = "unrelated"
    ISOLATED_CONFIRM = "isolated_confirm"


@dataclass(frozen=True)
class PendingReplyClassification:
    """Policy result for the current user input relative to a pending operation."""

    intent: PendingReplyIntent
    pending_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class HighRiskOperation:
    """A user-requested operation that must become pending before execution."""

    operation: str
    tool_name: str
    risk_level: RiskLevel
    scope_summary: str
    arguments: dict[str, object]
    reason: str


def classify_reply_to_pending(
    user_input: str,
    pending: PendingConfirmation | None,
) -> PendingReplyClassification:
    """Classify whether the user is confirming, cancelling, or changing pending work."""
    text = _normalize(user_input)

    if pending is None or not pending.is_pending:
        if _has_isolated_confirm_cue(text):
            return PendingReplyClassification(
                intent=PendingReplyIntent.ISOLATED_CONFIRM,
                reason="confirmation_without_active_pending",
            )
        return PendingReplyClassification(
            intent=PendingReplyIntent.UNRELATED,
            reason="no_active_pending",
        )

    if _has_modify_cue(text):
        return PendingReplyClassification(
            intent=PendingReplyIntent.MODIFY,
            pending_id=pending.id,
            reason="modify_cue",
        )
    if _has_cancel_cue(text):
        return PendingReplyClassification(
            intent=PendingReplyIntent.CANCEL,
            pending_id=pending.id,
            reason="cancel_cue",
        )
    if _has_confirm_cue(text):
        return PendingReplyClassification(
            intent=PendingReplyIntent.CONFIRM,
            pending_id=pending.id,
            reason="confirm_cue",
        )
    return PendingReplyClassification(
        intent=PendingReplyIntent.UNRELATED,
        pending_id=pending.id,
        reason="no_reply_cue",
    )


def detect_high_risk_operation(user_input: str) -> HighRiskOperation | None:
    """Return first-version destructive operations that require confirmation."""
    text = _normalize(user_input)

    todo_delete = _detect_bulk_todo_delete(text)
    if todo_delete is not None:
        return todo_delete

    memory_delete = _detect_risky_memory_delete(text)
    if memory_delete is not None:
        return memory_delete

    return None


def _detect_bulk_todo_delete(text: str) -> HighRiskOperation | None:
    if not _has_delete_cue(text):
        return None
    if not re.search(r"待办|任务|todo|todos|task|tasks", text):
        return None
    if not _has_bulk_cue(text):
        return None

    if re.search(r"已完成|完成的|done|completed", text):
        return HighRiskOperation(
            operation="delete_completed_todos",
            tool_name="delete_todo",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all completed todos",
            arguments={"status": "done"},
            reason="bulk_todo_delete",
        )

    return HighRiskOperation(
        operation="delete_all_todos",
        tool_name="delete_todo",
        risk_level=RiskLevel.HIGH,
        scope_summary="delete all todos",
        arguments={"scope": "all"},
        reason="bulk_todo_delete",
    )


def _detect_risky_memory_delete(text: str) -> HighRiskOperation | None:
    if not _has_memory_delete_cue(text):
        return None

    if _has_bulk_cue(text):
        return HighRiskOperation(
            operation="delete_all_memories",
            tool_name="delete_memory",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all active memories",
            arguments={"scope": "all_active"},
            reason="bulk_memory_delete",
        )

    if re.search(r"多条|几条|这些|那些|一批|multiple|several", text):
        return HighRiskOperation(
            operation="delete_multiple_memories",
            tool_name="delete_memory",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete multiple memories",
            arguments={"scope": "multiple"},
            reason="multiple_memory_delete",
        )

    if not re.search(r"\bmem_[a-z0-9_-]+\b", text):
        return HighRiskOperation(
            operation="delete_ambiguous_memory",
            tool_name="delete_memory",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete an ambiguous memory reference",
            arguments={"scope": "ambiguous"},
            reason="ambiguous_memory_delete",
        )

    return None


def _normalize(user_input: str) -> str:
    return user_input.strip().lower()


def _has_confirm_cue(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(确认|确定|是的|对|继续|执行|可以|没问题)\s*[。.!！]*$"
            r"|我确认|继续执行|继续删除|确认删除"
            r"|\b(?:yes|confirm|confirmed|ok|okay|proceed)\b",
            text,
        )
    )


def _has_isolated_confirm_cue(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(确认|确定|是的|对|可以|没问题)\s*[。.!！]*$"
            r"|我确认|确认删除"
            r"|\b(?:yes|confirm|confirmed|ok|okay|proceed)\b",
            text,
        )
    )


def _has_cancel_cue(text: str) -> bool:
    return bool(
        re.search(
            r"取消|算了|不要了|别删|停止|撤销|先别|不用了"
            r"|\b(?:no|cancel|stop|abort|never mind)\b",
            text,
        )
    )


def _has_modify_cue(text: str) -> bool:
    return bool(
        re.search(
            r"不是|改成|改为|只|仅|范围|别|除了|而是"
            r"|\b(?:instead|only|except|change|not all)\b",
            text,
        )
    )


def _has_delete_cue(text: str) -> bool:
    return bool(re.search(r"删除|移除|清空|删掉|delete|remove|clear", text))


def _has_bulk_cue(text: str) -> bool:
    return bool(re.search(r"所有|全部|全都|整个|清空|all|everything", text))


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
