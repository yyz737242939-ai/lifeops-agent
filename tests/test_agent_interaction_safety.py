import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent
from app.runtime.interaction_state import (
    InteractionState,
    PendingConfirmation,
    PendingConfirmationStatus,
    RiskLevel,
)


class AgentInteractionSafetyTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_bulk_todo_delete_creates_pending_without_llm_or_write_tool(
        self,
        create_response,
        events,
        _llm_io,
    ) -> None:
        agent = Agent()

        answer = agent.chat("删除所有已完成待办。")

        create_response.assert_not_called()
        pending = agent.interaction_state.active_pending_confirmation
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.operation, "delete_completed_todos")
        self.assertEqual(pending.tool_name, "delete_todo")
        self.assertIn("请回复“确认”", answer)
        events.log_interaction_pending.assert_called_once()
        event_call = events.log_interaction_pending.call_args
        self.assertEqual(event_call.args[1], "created")
        self.assertEqual(event_call.args[2].id, pending.id)
        self.assertEqual(event_call.kwargs["reason"], "bulk_todo_delete")

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_confirmed_pending_exposes_matching_write_tool_for_one_turn(
        self,
        create_response,
        events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="我会在确认范围内处理。",
        )
        agent = Agent()
        agent.chat("删除所有已完成待办。")

        answer = agent.chat("确认")

        self.assertEqual(answer, "我会在确认范围内处理。")
        sent_tools = create_response.call_args.kwargs["tools"]
        sent_tool_names = {schema["name"] for schema in sent_tools}
        self.assertIn("delete_todo", sent_tool_names)
        self.assertIsNone(agent.interaction_state.pending_confirmation)
        event_names = [
            call.args[1] for call in events.log_interaction_pending.call_args_list
        ]
        self.assertEqual(event_names, ["created", "confirmed", "consumed"])

    @patch("app.agents.agent.events")
    def test_pending_confirmation_only_authorizes_matching_write_tool(
        self,
        _events,
    ) -> None:
        agent = Agent()
        agent.chat("删除所有记忆。")
        confirmed = agent.interaction_state.confirm_pending()

        turn = agent._prepare_turn(
            "确认，并记住我喜欢早上学习。",
            agent.last_run_state,
            confirmed_pending=confirmed,
        )

        self.assertIn("delete_memory", turn.allowed_tool_names)
        self.assertNotIn("save_memory", turn.allowed_tool_names)

    @patch("app.agents.agent.events")
    def test_direct_prepare_turn_cannot_bypass_pending_with_confirmed_bulk_delete_text(
        self,
        _events,
    ) -> None:
        agent = Agent()

        turn = agent._prepare_turn(
            "我确认删除所有待办。",
            agent.last_run_state,
        )

        self.assertTrue(turn.bulk_delete_confirmation_required)
        self.assertNotIn("delete_todo", turn.allowed_tool_names)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_cancel_pending_finishes_without_llm_or_execution(
        self,
        create_response,
        events,
        _llm_io,
    ) -> None:
        agent = Agent()
        agent.chat("删除所有记忆。")
        create_response.reset_mock()
        events.log_interaction_pending.reset_mock()

        answer = agent.chat("算了，不要了。")

        create_response.assert_not_called()
        self.assertIn("已取消", answer)
        self.assertIsNone(agent.interaction_state.active_pending_confirmation)
        self.assertEqual(
            agent.interaction_state.pending_confirmation.status,
            PendingConfirmationStatus.CANCELLED,
        )
        events.log_interaction_pending.assert_called_once()
        self.assertEqual(events.log_interaction_pending.call_args.args[1], "cancelled")

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_expired_pending_confirmation_requires_restatement(
        self,
        create_response,
        events,
        _llm_io,
    ) -> None:
        agent = Agent()
        agent.interaction_state = InteractionState(
            pending_confirmation=PendingConfirmation(
                operation="delete_all_memories",
                tool_name="delete_memory",
                risk_level=RiskLevel.HIGH,
                scope_summary="delete all active memories",
                arguments={"scope": "all_active"},
                source_user_input="删除所有记忆。",
                created_turn_index=0,
                expires_after_turns=1,
            ),
            turn_index=1,
        )

        answer = agent.chat("确认")

        create_response.assert_not_called()
        self.assertIn("已经过期", answer)
        self.assertEqual(
            agent.interaction_state.pending_confirmation.status,
            PendingConfirmationStatus.EXPIRED,
        )
        events.log_interaction_pending.assert_called_once()
        self.assertEqual(events.log_interaction_pending.call_args.args[1], "expired")

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_modified_scope_supersedes_old_pending_and_creates_new_one(
        self,
        create_response,
        events,
        _llm_io,
    ) -> None:
        agent = Agent()
        agent.chat("删除所有待办。")
        first_pending = agent.interaction_state.pending_confirmation
        create_response.reset_mock()
        events.log_interaction_pending.reset_mock()

        answer = agent.chat("不是全部，只删除所有已完成待办。")

        create_response.assert_not_called()
        self.assertIn("请回复“确认”", answer)
        self.assertEqual(first_pending.status, PendingConfirmationStatus.SUPERSEDED)
        pending = agent.interaction_state.active_pending_confirmation
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.operation, "delete_completed_todos")
        event_names = [
            call.args[1] for call in events.log_interaction_pending.call_args_list
        ]
        self.assertEqual(event_names, ["superseded", "created"])

    @patch("app.agents.agent.events")
    def test_interaction_pending_event_omits_source_user_input(
        self,
        events,
    ) -> None:
        agent = Agent()

        agent.chat("删除所有记忆。")

        logged_pending = events.log_interaction_pending.call_args.args[2]
        self.assertEqual(logged_pending.source_user_input, "删除所有记忆。")
        logged_kwargs = events.log_interaction_pending.call_args.kwargs
        self.assertNotIn("source_user_input", logged_kwargs)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_ordinary_writes_do_not_require_interaction_pending(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="已处理。",
        )
        agent = Agent()

        agent.chat("添加一个待办：整理书桌。")

        sent_tools = create_response.call_args.kwargs["tools"]
        sent_tool_names = {schema["name"] for schema in sent_tools}
        self.assertIn("add_todo", sent_tool_names)
        self.assertIsNone(agent.interaction_state.active_pending_confirmation)


if __name__ == "__main__":
    unittest.main()
