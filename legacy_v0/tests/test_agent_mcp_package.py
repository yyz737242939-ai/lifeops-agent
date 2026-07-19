import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent


def _function_call(name: str, arguments: dict[str, object], call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
        call_id=call_id,
    )


def _tool_names(call) -> set[str]:
    return {schema["name"] for schema in call.kwargs["tools"]}


class AgentMcpPackageTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_package_tracking_runs_through_agent_mcp_tool_loop(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.side_effect = [
            SimpleNamespace(
                output=[
                    _function_call(
                        "track_package_via_mcp",
                        {"tracking_number": "PKG-001"},
                        "call_pkg_1",
                    )
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[],
                output_text="PKG-001 当前在 Shanghai sorting center，状态是 in_transit。",
            ),
        ]
        agent = Agent()

        answer = agent.chat("查一下 PKG-001 到哪了")

        self.assertIn("PKG-001", answer)
        self.assertIn("in_transit", answer)
        first_tools = _tool_names(create_response.call_args_list[0])
        self.assertIn("track_package_via_mcp", first_tools)
        self.assertIn("list_package_updates_via_mcp", first_tools)
        self.assertIn("estimate_delivery_window_via_mcp", first_tools)
        self.assertNotIn("add_todo", first_tools)
        self.assertNotIn("record_expense", first_tools)
        self.assertNotIn("save_memory", first_tools)

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(
            [action.tool_name for action in state.completed_action_records],
            ["track_package_via_mcp"],
        )

        outputs = [
            message["output"]
            for message in agent.messages
            if isinstance(message, dict)
            and message.get("type") == "function_call_output"
        ]
        self.assertEqual(len(outputs), 1)
        observation = json.loads(outputs[0])
        self.assertTrue(observation["ok"])
        self.assertEqual(observation["mcp"]["server_id"], "mock_package_tracking")
        self.assertEqual(observation["mcp"]["tool_name"], "track_package")
        self.assertEqual(observation["result"]["tracking_number"], "PKG-001")

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_missing_package_mcp_error_reaches_final_answer_without_memory_write(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.side_effect = [
            SimpleNamespace(
                output=[
                    _function_call(
                        "track_package_via_mcp",
                        {"tracking_number": "PKG-404"},
                        "call_pkg_404",
                    )
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[],
                output_text="没有查到 PKG-404 的物流记录。",
            ),
        ]
        agent = Agent()

        answer = agent.chat("查一下 PKG-404 到哪了")

        self.assertIn("没有查到", answer)
        state = agent.last_run_state
        assert state is not None
        self.assertEqual(
            [action.tool_name for action in state.action_records],
            ["track_package_via_mcp"],
        )
        self.assertEqual(
            state.failed_action_records[0].tool_name,
            "track_package_via_mcp",
        )

        outputs = [
            message["output"]
            for message in agent.messages
            if isinstance(message, dict)
            and message.get("type") == "function_call_output"
        ]
        observation = json.loads(outputs[0])
        self.assertFalse(observation["ok"])
        self.assertEqual(observation["error"]["code"], "package_not_found")
        self.assertNotIn("save_memory", outputs[0])


if __name__ == "__main__":
    unittest.main()
