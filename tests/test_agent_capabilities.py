import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent


class AgentCapabilityTests(unittest.TestCase):
    @patch("app.agents.agent.log_raw_event")
    @patch("app.agents.agent.log_event")
    @patch("app.agents.agent.client.responses.create")
    def test_agent_sends_only_selected_capability_schemas(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="done",
        )
        agent = Agent()

        agent.chat("列出我的待办任务")

        sent_tools = create_response.call_args.kwargs["tools"]
        sent_names = {schema["name"] for schema in sent_tools}
        self.assertIn("list_todos", sent_names)
        self.assertIn("read_context_ref", sent_names)
        self.assertNotIn("record_expense", sent_names)
        self.assertNotIn("recommend_activities", sent_names)

        capability_events = [
            call.kwargs
            for call in _log_event.call_args_list
            if call.args == ("capability_build",)
        ]
        self.assertEqual(len(capability_events), 1)
        self.assertEqual(set(capability_events[0]["visible_tool_names"]), sent_names)
        self.assertEqual(capability_events[0]["loaded_skills"], ["todo"])

        raw_requests = [
            call.kwargs
            for call in _log_raw_event.call_args_list
            if call.args == ("llm_request",)
        ]
        self.assertEqual(len(raw_requests), 1)
        self.assertEqual(
            {schema["name"] for schema in raw_requests[0]["tools"]},
            sent_names,
        )

    @patch("app.agents.agent.log_raw_event")
    @patch("app.agents.agent.log_event")
    @patch("app.agents.agent.client.responses.create")
    @patch("app.tools.tool.expense_store.add_expense")
    def test_agent_logs_and_blocks_a_denied_tool_call(
        self,
        add_expense,
        create_response,
        log_event,
        _log_raw_event,
    ) -> None:
        denied_call = SimpleNamespace(
            type="function_call",
            name="record_expense",
            arguments='{"amount":35,"category":"food","description":"lunch"}',
            call_id="call-denied",
        )
        create_response.side_effect = [
            SimpleNamespace(output=[denied_call], output_text=""),
            SimpleNamespace(output=[], output_text="permission denied"),
        ]
        agent = Agent()

        answer = agent.chat("列出我的待办任务")

        self.assertEqual(answer, "permission denied")
        add_expense.assert_not_called()
        denied_events = [
            call.kwargs
            for call in log_event.call_args_list
            if call.args == ("tool_denied",)
        ]
        self.assertEqual(len(denied_events), 1)
        self.assertEqual(denied_events[0]["tool_call_name"], "record_expense")
        self.assertEqual(denied_events[0]["error"], "tool_not_allowed")


if __name__ == "__main__":
    unittest.main()
