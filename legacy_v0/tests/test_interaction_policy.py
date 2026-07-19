import unittest

from app.runtime.interaction_policy import (
    PendingReplyIntent,
    classify_reply_to_pending,
    detect_high_risk_operation,
)
from app.runtime.interaction_state import PendingConfirmation, RiskLevel


def _pending() -> PendingConfirmation:
    return PendingConfirmation(
        id="pending-test",
        operation="delete_completed_todos",
        tool_name="delete_todo",
        risk_level=RiskLevel.HIGH,
        scope_summary="delete all completed todos",
        arguments={"status": "done"},
        source_user_input="删除所有已完成待办。",
    )


class PendingReplyPolicyTests(unittest.TestCase):
    def test_classifies_confirmation_when_pending_is_active(self) -> None:
        result = classify_reply_to_pending("确认。", _pending())

        self.assertEqual(result.intent, PendingReplyIntent.CONFIRM)
        self.assertEqual(result.pending_id, "pending-test")

    def test_classifies_cancellation_when_pending_is_active(self) -> None:
        result = classify_reply_to_pending("算了，不要删了。", _pending())

        self.assertEqual(result.intent, PendingReplyIntent.CANCEL)
        self.assertEqual(result.pending_id, "pending-test")

    def test_modify_cue_takes_precedence_over_confirmation(self) -> None:
        result = classify_reply_to_pending("确认，但只删除今天完成的。", _pending())

        self.assertEqual(result.intent, PendingReplyIntent.MODIFY)
        self.assertEqual(result.pending_id, "pending-test")

    def test_isolated_confirmation_does_not_authorize_without_pending(self) -> None:
        result = classify_reply_to_pending("确认", None)

        self.assertEqual(result.intent, PendingReplyIntent.ISOLATED_CONFIRM)
        self.assertIsNone(result.pending_id)

    def test_continue_without_pending_is_not_treated_as_confirmation(self) -> None:
        result = classify_reply_to_pending("继续", None)

        self.assertEqual(result.intent, PendingReplyIntent.UNRELATED)
        self.assertIsNone(result.pending_id)

    def test_unrelated_input_is_not_treated_as_confirmation(self) -> None:
        result = classify_reply_to_pending("今天天气怎么样？", _pending())

        self.assertEqual(result.intent, PendingReplyIntent.UNRELATED)
        self.assertEqual(result.pending_id, "pending-test")

    def test_terminal_pending_is_treated_as_no_active_pending(self) -> None:
        pending = _pending()
        pending.cancel()

        result = classify_reply_to_pending("确认", pending)

        self.assertEqual(result.intent, PendingReplyIntent.ISOLATED_CONFIRM)
        self.assertIsNone(result.pending_id)


class HighRiskOperationPolicyTests(unittest.TestCase):
    def test_detects_bulk_completed_todo_delete(self) -> None:
        result = detect_high_risk_operation("删除所有已完成待办。")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.operation, "delete_completed_todos")
        self.assertEqual(result.tool_name, "delete_todo")
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertEqual(result.arguments, {"status": "done"})

    def test_detects_all_todo_delete(self) -> None:
        result = detect_high_risk_operation("清空全部 todo。")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.operation, "delete_all_todos")
        self.assertEqual(result.arguments, {"scope": "all"})

    def test_single_todo_delete_is_not_first_version_high_risk(self) -> None:
        self.assertIsNone(detect_high_risk_operation("删除 todo 42。"))

    def test_detects_all_memory_delete(self) -> None:
        result = detect_high_risk_operation("删除所有记忆。")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.operation, "delete_all_memories")
        self.assertEqual(result.tool_name, "delete_memory")
        self.assertEqual(result.arguments, {"scope": "all_active"})

    def test_detects_multiple_memory_delete(self) -> None:
        result = detect_high_risk_operation("删除这些记忆。")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.operation, "delete_multiple_memories")
        self.assertEqual(result.arguments, {"scope": "multiple"})

    def test_detects_ambiguous_memory_delete(self) -> None:
        result = detect_high_risk_operation("忘掉这条记忆。")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.operation, "delete_ambiguous_memory")
        self.assertEqual(result.arguments, {"scope": "ambiguous"})

    def test_specific_memory_id_delete_is_not_first_version_high_risk(self) -> None:
        self.assertIsNone(detect_high_risk_operation("删除记忆 mem_20260705_test。"))

    def test_ordinary_writes_do_not_require_interaction_confirmation(self) -> None:
        self.assertIsNone(detect_high_risk_operation("添加一个待办：整理书桌。"))
        self.assertIsNone(detect_high_risk_operation("记住我喜欢早上学习。"))


if __name__ == "__main__":
    unittest.main()
