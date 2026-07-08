import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent


class AgentCapabilityTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
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

        capability_call = _log_event.log_capabilities_built.call_args
        self.assertIsNotNone(capability_call)
        capabilities = capability_call.args[1]
        self.assertEqual(
            {schema["name"] for schema in capabilities.tool_schemas}, sent_names
        )
        self.assertEqual(capabilities.loaded_skills, ("todo",))

        raw_request = _log_raw_event.log_request.call_args
        self.assertIsNotNone(raw_request)
        self.assertEqual(
            {schema["name"] for schema in raw_request.kwargs["tools"]},
            sent_names,
        )
        self.assertEqual(
            create_response.call_args.kwargs["input"],
            raw_request.kwargs["input_messages"],
        )
        context_parameters = raw_request.kwargs["parameters"]["context_engine"]
        self.assertEqual(context_parameters["mode"], "pass_through_with_units")
        self.assertEqual(context_parameters["message_count"], 1)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
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
        denied_call = log_event.log_tool_denied.call_args
        self.assertIsNotNone(denied_call)
        self.assertEqual(denied_call.args[2].name, "record_expense")


if __name__ == "__main__":
    unittest.main()
