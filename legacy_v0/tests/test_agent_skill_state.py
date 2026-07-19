import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent
from app.tools.capability_builder import COMMON_TOOL_NAMES, SKILL_TOOL_NAMES
from app.tools.tool import TOOLS, ToolEffect


def _tool_names(call) -> set[str]:
    return {schema["name"] for schema in call.kwargs["tools"]}


def _common_read_tools() -> set[str]:
    return {
        name
        for name in COMMON_TOOL_NAMES
        if TOOLS[name].effect == ToolEffect.READ
    }


def _read_tools(skill_name: str) -> set[str]:
    return _common_read_tools() | {
        name
        for name in SKILL_TOOL_NAMES[skill_name]
        if TOOLS[name].effect == ToolEffect.READ
    }


class AgentSkillStateTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_todo_followup_inherits_skill_and_capabilities(
        self,
        create_response,
        log_event,
        _log_raw_event,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        agent = Agent()

        agent.chat("列出我的待办任务")
        agent.chat("完成第一个")

        first_tools = _tool_names(create_response.call_args_list[0])
        second_tools = _tool_names(create_response.call_args_list[1])
        self.assertEqual(first_tools, _read_tools("todo"))
        self.assertEqual(second_tools, _read_tools("todo") | {"complete_todo"})
        self.assertEqual(agent.active_skills, ("todo",))

        routing_calls = log_event.log_routing_resolved.call_args_list
        followup = routing_calls[1].kwargs["skill_state"]
        self.assertEqual(followup.directly_selected, ())
        self.assertEqual(followup.inherited_skills, ("todo",))
        self.assertEqual(followup.loaded_skills, ("todo",))
        self.assertTrue(followup.inheritance_used)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_explicit_switch_replaces_old_skill_and_chat_clears_it(
        self,
        create_response,
        log_event,
        _log_raw_event,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        agent = Agent()

        agent.chat("列出我的待办任务")
        agent.chat("检查本周餐饮预算")
        agent.chat("你好，介绍一下自己")

        finance_tools = _tool_names(create_response.call_args_list[1])
        fallback_tools = _tool_names(create_response.call_args_list[2])
        self.assertEqual(
            finance_tools,
            _read_tools("finance"),
        )
        self.assertTrue(finance_tools.isdisjoint(SKILL_TOOL_NAMES["todo"]))
        self.assertEqual(fallback_tools, _common_read_tools())
        self.assertEqual(agent.active_skills, ())

        routing_calls = log_event.log_routing_resolved.call_args_list
        second_state = routing_calls[1].kwargs["skill_state"]
        third_state = routing_calls[2].kwargs["skill_state"]
        self.assertEqual(second_state.directly_selected, ("finance",))
        self.assertEqual(second_state.inherited_skills, ())
        self.assertTrue(third_state.state_cleared)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_ref_turn_uses_common_tools_but_preserves_topic_for_next_followup(
        self,
        create_response,
        log_event,
        _log_raw_event,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        agent = Agent()

        agent.chat("列出最近的消费记录")
        agent.chat("把刚才引用的完整结果展开")
        self.assertEqual(agent.active_skills, ("finance",))
        agent.chat("继续")

        ref_tools = _tool_names(create_response.call_args_list[1])
        continued_tools = _tool_names(create_response.call_args_list[2])
        self.assertEqual(ref_tools, _common_read_tools())
        self.assertEqual(
            continued_tools,
            _read_tools("finance"),
        )

        routing_calls = log_event.log_routing_resolved.call_args_list
        ref_state = routing_calls[1].kwargs["skill_state"]
        continued_state = routing_calls[2].kwargs["skill_state"]
        self.assertEqual(ref_state.resolution, "context_ref_only")
        self.assertEqual(ref_state.loaded_skills, ())
        self.assertEqual(continued_state.inherited_skills, ("finance",))

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_news_turn_exposes_reference_source_and_helper_tools(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        agent = Agent()

        agent.chat("总结今天 Hugging Face 上的热门论文和博客")

        tools = _tool_names(create_response.call_args)
        self.assertIn("read_skill_reference", tools)
        self.assertIn("fetch_news_source", tools)
        self.assertIn("run_news_helper", tools)
        self.assertEqual(agent.active_skills, ("news",))

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_skill_reference_body_is_ephemeral_within_news_turn(
        self,
        create_response,
        _log_event,
        _log_raw_event,
    ) -> None:
        reference_call = SimpleNamespace(
            type="function_call",
            name="read_skill_reference",
            arguments='{"ref_id": "briefing_policy"}',
            call_id="call_ref_1",
        )
        create_response.side_effect = [
            SimpleNamespace(output=[reference_call], output_text=""),
            SimpleNamespace(output=[], output_text="done"),
        ]
        agent = Agent()

        agent.chat("总结今天 Hugging Face 上的热门论文和博客")

        outputs = [
            message["output"]
            for message in agent.messages
            if isinstance(message, dict)
            and message.get("type") == "function_call_output"
        ]
        self.assertEqual(len(outputs), 1)
        self.assertIn("content_omitted", outputs[0])
        self.assertNotIn("Briefing Policy", outputs[0])


if __name__ == "__main__":
    unittest.main()
