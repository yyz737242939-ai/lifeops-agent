import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent
from app.runtime.run_state import RunState
from app.runtime.run_state import ActionRecord, ActionStatus
from app.runtime.write_policy import (
    authorized_write_tools,
    has_write_success_claim,
    requires_bulk_delete_confirmation,
)


def _response(text: str) -> SimpleNamespace:
    return SimpleNamespace(output=[], output_text=text)


class WritePolicyTests(unittest.TestCase):
    def test_advice_context_does_not_authorize_wellbeing_write(self) -> None:
        tools = authorized_write_tools(
            "我今天能量低，只有20分钟，推荐一个恢复活动。"
        )

        self.assertNotIn("record_daily_state", tools)

    def test_historical_record_reference_does_not_authorize_new_write(self) -> None:
        tools = authorized_write_tools("根据我之前记录的低能量状态推荐活动。")

        self.assertNotIn("record_daily_state", tools)

    def test_explicit_wellbeing_record_authorizes_write(self) -> None:
        tools = authorized_write_tools("记录今天能量低，心情一般。")

        self.assertIn("record_daily_state", tools)

    def test_explicit_wellbeing_update_authorizes_write(self) -> None:
        tools = authorized_write_tools("把今天的状态更新为睡眠6小时。")

        self.assertIn("record_daily_state", tools)

    def test_descriptive_todo_add_authorizes_write(self) -> None:
        tools = authorized_write_tools("添加一个低优先级待办：整理书桌。")

        self.assertIn("add_todo", tools)

    def test_mixed_language_todo_add_authorizes_write(self) -> None:
        tools = authorized_write_tools("请帮我添加一个 todo：明天上午复盘 MCP 测试计划。")

        self.assertIn("add_todo", tools)

    def test_repeat_mixed_language_todo_add_authorizes_write(self) -> None:
        tools = authorized_write_tools("请再添加一个 todo：整理 ContextEngine 学习笔记。")

        self.assertIn("add_todo", tools)

    def test_mark_quoted_todo_complete_authorizes_write(self) -> None:
        tools = authorized_write_tools("把刚才那个“复盘 MCP 测试计划”的 todo 标记为完成。")

        self.assertIn("complete_todo", tools)

    def test_explicit_expense_record_authorizes_write(self) -> None:
        tools = authorized_write_tools("今天午饭花了35元，记到餐饮。")

        self.assertIn("record_expense", tools)

    def test_descriptive_preference_does_not_authorize_memory_write(self) -> None:
        tools = authorized_write_tools("我喜欢早上学习。")

        self.assertNotIn("save_memory", tools)

    def test_explicit_memory_save_authorizes_save_memory(self) -> None:
        tools = authorized_write_tools("记住我喜欢早上学习。")

        self.assertIn("save_memory", tools)

    def test_explicit_memory_delete_authorizes_delete_memory_only(self) -> None:
        tools = authorized_write_tools("忘掉这条记忆。")

        self.assertIn("delete_memory", tools)
        self.assertNotIn("save_memory", tools)
        self.assertNotIn("delete_todo", tools)

    def test_descriptive_goal_does_not_authorize_task_write(self) -> None:
        tools = authorized_write_tools("我想下周完成 Task State v1。")

        self.assertNotIn("create_task", tools)
        self.assertNotIn("update_task_status", tools)

    def test_explicit_task_create_authorizes_create_task(self) -> None:
        tools = authorized_write_tools("帮我创建任务：完成 Task State v1。")

        self.assertIn("create_task", tools)

    def test_explicit_task_progress_updates_authorize_task_writes(self) -> None:
        tools = authorized_write_tools(
            "把这个任务标记完成，并记录进展 note：Step 4 已完成。"
        )

        self.assertIn("update_task_status", tools)
        self.assertIn("add_task_note", tools)

    def test_continue_task_is_read_only_not_status_write(self) -> None:
        tools = authorized_write_tools("继续上次任务。")

        self.assertNotIn("update_task_status", tools)

    def test_explicit_task_blocker_authorizes_blocker_write(self) -> None:
        tools = authorized_write_tools("这个任务卡住了，原因是需要先确认授权边界。")

        self.assertIn("add_task_blocker", tools)

    def test_bulk_delete_requires_confirmation(self) -> None:
        self.assertTrue(requires_bulk_delete_confirmation("删除所有待办。"))
        self.assertNotIn("delete_todo", authorized_write_tools("删除所有待办。"))

    def test_confirmed_bulk_delete_is_authorized(self) -> None:
        text = "我确认删除所有待办。"

        self.assertFalse(requires_bulk_delete_confirmation(text))
        self.assertIn("delete_todo", authorized_write_tools(text))

    def test_success_claim_detection_ignores_failure_message(self) -> None:
        self.assertTrue(has_write_success_claim("已记录今天早餐18元。"))
        self.assertTrue(has_write_success_claim("已创建任务：Task State v1。"))
        self.assertFalse(has_write_success_claim("抱歉，无法记录这笔消费。"))
        self.assertFalse(
            has_write_success_claim("只有成功的 WRITE action 才能证明真的保存了。")
        )

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_model_cannot_claim_write_without_successful_action(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = _response("已记录今天早餐18元。")
        agent = Agent()

        answer = agent.chat("今天早餐18元。")

        self.assertIn("没有收到任何成功的写入结果", answer)
        self.assertNotEqual(answer, "已记录今天早餐18元。")

    def test_partial_write_claim_names_failed_write(self) -> None:
        state = RunState(run_id="test-run")
        state.add_action(
            ActionRecord(
                call_id="call-1",
                tool_name="add_todo",
                arguments={"title": "测试"},
                status=ActionStatus.COMPLETED,
            )
        )
        state.add_action(
            ActionRecord(
                call_id="call-2",
                tool_name="record_expense",
                arguments={"amount": 10},
                status=ActionStatus.FAILED,
            )
        )

        answer = Agent._validate_final_answer("已添加待办并记录消费。", state)

        self.assertIn("写入未全部成功", answer)
        self.assertIn("record_expense", answer)

    def test_prepare_turn_filters_unauthorized_write_tools(self) -> None:
        agent = Agent()

        with patch("app.agents.agent.events"):
            turn = agent._prepare_turn(
                "我今天能量低，推荐一个恢复活动。",
                RunState(run_id="test-run"),
            )

        self.assertNotIn("record_daily_state", turn.allowed_tool_names)
        self.assertIn("recommend_activities", turn.allowed_tool_names)

    def test_prepare_turn_allows_explicit_wellbeing_write(self) -> None:
        agent = Agent()

        with patch("app.agents.agent.events"):
            turn = agent._prepare_turn(
                "记录今天能量低。",
                RunState(run_id="test-run"),
            )

        self.assertIn("record_daily_state", turn.allowed_tool_names)

    def test_prepare_turn_blocks_unconfirmed_bulk_delete(self) -> None:
        agent = Agent()

        with patch("app.agents.agent.events"):
            turn = agent._prepare_turn(
                "删除所有待办。",
                RunState(run_id="test-run"),
            )

        self.assertTrue(turn.bulk_delete_confirmation_required)
        self.assertNotIn("delete_todo", turn.allowed_tool_names)


if __name__ == "__main__":
    unittest.main()
