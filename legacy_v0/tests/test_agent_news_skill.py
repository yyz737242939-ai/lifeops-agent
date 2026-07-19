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


class AgentNewsSkillTests(unittest.TestCase):
    @patch("app.tools.tool.fetch_skill_source")
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_hugging_face_briefing_runs_reference_source_helper_loop(
        self,
        create_response,
        _events,
        _llm_io,
        fetch_source,
    ) -> None:
        papers_html = (
            '<a href="/papers/2501.00001">Agentic Retrieval for LLMs</a>'
            '<a href="/papers/2501.00002">Multimodal Video Reasoning</a>'
        )
        blog_html = (
            '<a href="/blog/smolagents">Smolagents agent workflows</a>'
            '<a href="/blog/vlm">Vision language models in practice</a>'
        )
        fetch_source.side_effect = [
            {
                "ok": True,
                "action": "fetch_news_source",
                "skill": "news",
                "source_id": "hf_daily_papers",
                "name": "Hugging Face Daily Papers",
                "url": "https://huggingface.co/papers",
                "kind": "html",
                "fetched_at": "2026-07-02T00:00:00+00:00",
                "status": 200,
                "content_type": "text/html",
                "chars": len(papers_html),
                "truncated": False,
                "content": papers_html,
                "error": None,
            },
            {
                "ok": True,
                "action": "fetch_news_source",
                "skill": "news",
                "source_id": "hf_blog",
                "name": "Hugging Face Blog",
                "url": "https://huggingface.co/blog",
                "kind": "html",
                "fetched_at": "2026-07-02T00:00:00+00:00",
                "status": 200,
                "content_type": "text/html",
                "chars": len(blog_html),
                "truncated": False,
                "content": blog_html,
                "error": None,
            },
        ]
        create_response.side_effect = [
            SimpleNamespace(
                output=[
                    _function_call(
                        "read_skill_reference",
                        {"ref_id": "briefing_policy"},
                        "call_ref",
                    )
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[
                    _function_call(
                        "fetch_news_source",
                        {"source_id": "hf_daily_papers"},
                        "call_papers",
                    ),
                    _function_call(
                        "fetch_news_source",
                        {"source_id": "hf_blog"},
                        "call_blog",
                    ),
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[
                    _function_call(
                        "run_news_helper",
                        {
                            "helper_id": "parse_hf_daily_papers",
                            "arguments": {"html": papers_html, "limit": 5},
                        },
                        "call_parse_papers",
                    ),
                    _function_call(
                        "run_news_helper",
                        {
                            "helper_id": "parse_hf_blog",
                            "arguments": {"html": blog_html, "limit": 5},
                        },
                        "call_parse_blog",
                    ),
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[
                    _function_call(
                        "run_news_helper",
                        {
                            "helper_id": "rank_news_items",
                            "arguments": {
                                "items": [
                                    {
                                        "title": "Agentic Retrieval for LLMs",
                                        "url": "https://huggingface.co/papers/2501.00001",
                                        "source_id": "hf_daily_papers",
                                        "score_or_votes": None,
                                        "raw_position": 1,
                                    },
                                    {
                                        "title": "Smolagents agent workflows",
                                        "url": "https://huggingface.co/blog/smolagents",
                                        "source_id": "hf_blog",
                                        "score_or_votes": None,
                                        "raw_position": 2,
                                    },
                                ],
                                "limit": 5,
                            },
                        },
                        "call_rank",
                    )
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[],
                output_text=(
                    "基于 Hugging Face 列表页可见信息："
                    "论文：Agentic Retrieval for LLMs。"
                    "博客：Smolagents agent workflows。"
                ),
            ),
        ]
        agent = Agent()

        answer = agent.chat("总结今天 Hugging Face 上的热门论文和博客")

        self.assertIn("基于 Hugging Face 列表页可见信息", answer)
        self.assertIn("Agentic Retrieval for LLMs", answer)
        self.assertIn("Smolagents agent workflows", answer)
        tools = _tool_names(create_response.call_args_list[0])
        self.assertIn("read_skill_reference", tools)
        self.assertIn("fetch_news_source", tools)
        self.assertIn("run_news_helper", tools)
        self.assertNotIn("save_memory", tools)

        state = agent.last_run_state
        assert state is not None
        self.assertEqual(
            [action.tool_name for action in state.completed_action_records],
            [
                "read_skill_reference",
                "fetch_news_source",
                "fetch_news_source",
                "run_news_helper",
                "run_news_helper",
                "run_news_helper",
            ],
        )
        fetch_source.assert_any_call("news", "hf_daily_papers")
        fetch_source.assert_any_call("news", "hf_blog")

        stored_outputs = [
            message["output"]
            for message in agent.messages
            if isinstance(message, dict)
            and message.get("type") == "function_call_output"
        ]
        self.assertTrue(any("ephemeral_source" in output for output in stored_outputs))
        self.assertFalse(any(papers_html in output for output in stored_outputs))
        self.assertFalse(any(blog_html in output for output in stored_outputs))

    @patch("app.tools.tool.fetch_skill_source")
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_failed_source_fetch_remains_structured_and_does_not_run_helper(
        self,
        create_response,
        _events,
        _llm_io,
        fetch_source,
    ) -> None:
        fetch_source.return_value = {
            "ok": False,
            "action": "fetch_news_source",
            "error": "source_fetch_failed",
            "message": "network unavailable",
            "skill": "news",
            "source_id": "hf_blog",
            "url": "https://huggingface.co/blog",
            "fetched_at": "2026-07-02T00:00:00+00:00",
            "status": None,
        }
        create_response.side_effect = [
            SimpleNamespace(
                output=[
                    _function_call(
                        "fetch_news_source",
                        {"source_id": "hf_blog"},
                        "call_blog",
                    )
                ],
                output_text="",
            ),
            SimpleNamespace(
                output=[],
                output_text="Hugging Face Blog 读取失败，无法生成基于实时来源的简报。",
            ),
        ]
        agent = Agent()

        answer = agent.chat("把 Hugging Face Blog 最近热门文章整理成中文简报")

        self.assertIn("读取失败", answer)
        state = agent.last_run_state
        assert state is not None
        self.assertEqual(
            [action.tool_name for action in state.action_records],
            ["fetch_news_source"],
        )
        self.assertEqual(state.failed_action_records[0].tool_name, "fetch_news_source")


if __name__ == "__main__":
    unittest.main()
