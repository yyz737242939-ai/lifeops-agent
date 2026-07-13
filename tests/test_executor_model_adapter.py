from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.executor.errors import ExecutorModelError, InvalidExecutorModelActionError
from app.executor.model_adapter import OpenAIExecutorModelClient
from app.executor.models import (
    ExecutorContextContribution,
    ExecutorMemoryContribution,
    ExecutorModelInput,
    FinalAnswerDecision,
    ToolActionDecision,
    ToolObservation,
)
from app.runtime.models import RuntimeRequest
from app.skills.models import PromptContribution
from app.tools.models import ToolCallStatus, ToolError


_CATALOG = (
    {
        "name": "travel.search_places",
        "description": "Search places.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
)


class OpenAIExecutorModelClientTest(unittest.TestCase):
    @patch("app.executor.model_adapter.load_dotenv")
    @patch("app.executor.model_adapter.OpenAI")
    def test_function_call_uses_only_filtered_catalog_and_typed_input(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        api = _FakeOpenAIClient(
            _response(
                calls=[
                    _function_call(
                        "call_1",
                        "travel.search_places",
                        {"query": "Tokyo"},
                    )
                ]
            )
        )
        openai_type.return_value = api
        client = _configured_client()

        decision = client.decide(_model_input())

        self.assertIsInstance(decision, ToolActionDecision)
        self.assertEqual(decision.call.arguments, {"query": "Tokyo"})
        call = api.responses.calls[0]
        self.assertFalse(call["parallel_tool_calls"])
        self.assertEqual(call["max_tool_calls"], 1)
        self.assertEqual([item["name"] for item in call["tools"]], ["travel.search_places"])
        self.assertNotIn("previous_response_id", call)
        payload = json.loads(call["input"])
        self.assertEqual(payload["step_index"], 2)
        self.assertEqual(payload["context"][0]["source"], "context://1")
        self.assertEqual(payload["memory"][0]["source"], "memory://1")
        self.assertNotIn("private-tool-argument", call["input"])

    @patch("app.executor.model_adapter.load_dotenv")
    @patch("app.executor.model_adapter.OpenAI")
    def test_non_empty_output_text_becomes_final_answer(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        openai_type.return_value = _FakeOpenAIClient(
            _response(output_text="这是最终回答。")
        )
        client = _configured_client()

        decision = client.decide(_model_input())

        self.assertEqual(decision, FinalAnswerDecision("这是最终回答。"))

    @patch("app.executor.model_adapter.load_dotenv")
    @patch("app.executor.model_adapter.OpenAI")
    def test_invalid_provider_actions_fail_closed(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        cases = (
            _response(),
            _response(output_text="answer", calls=[_function_call("call_1", "travel.search_places", {})]),
            _response(calls=[_function_call("call_1", "travel.search_places", {}), _function_call("call_2", "travel.search_places", {})]),
            _response(calls=[_function_call("call_1", "unknown.tool", {})]),
            _response(calls=[SimpleNamespace(type="function_call", call_id="call_1", name="travel.search_places", arguments="[]")]),
            _response(calls=[SimpleNamespace(type="function_call", call_id="call_1", name="travel.search_places", arguments="not-json")]),
        )
        for response in cases:
            with self.subTest(response=response):
                openai_type.return_value = _FakeOpenAIClient(response)
                client = _configured_client()
                with self.assertRaises(InvalidExecutorModelActionError):
                    client.decide(_model_input())

    @patch("app.executor.model_adapter.load_dotenv")
    @patch("app.executor.model_adapter.OpenAI")
    def test_provider_exception_is_a_safe_typed_failure(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        openai_type.return_value = _FakeOpenAIClient(
            RuntimeError("private-provider-path")
        )
        client = _configured_client()

        with self.assertRaises(ExecutorModelError) as caught:
            client.decide(_model_input())

        self.assertEqual(caught.exception.code, "executor_model_provider_failed")
        self.assertNotIn("private-provider-path", str(caught.exception))

    @patch("app.executor.model_adapter.load_dotenv")
    @patch("app.executor.model_adapter.OpenAI")
    def test_records_success_and_invalid_action_interactions(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        sink = _RecordingLlmSink()
        openai_type.return_value = _FakeOpenAIClient(
            _response(output_text="完成。")
        )
        client = _configured_client()

        client.decide(_model_input(), llm_log=sink)

        self.assertEqual(len(sink.records), 1)
        success = sink.records[0]
        self.assertEqual(success["provider"], "openai-compatible")
        self.assertEqual(success["model"], "test-model")
        self.assertEqual(success["status"], "ok")
        self.assertEqual(success["response"]["output_text"], "完成。")
        self.assertEqual(
            json.loads(success["request"]["input"])["step_index"], 2
        )

        invalid_sink = _RecordingLlmSink()
        openai_type.return_value = _FakeOpenAIClient(_response())
        invalid_client = _configured_client()
        with self.assertRaises(InvalidExecutorModelActionError):
            invalid_client.decide(_model_input(), llm_log=invalid_sink)
        self.assertEqual(invalid_sink.records[0]["status"], "failed")
        self.assertEqual(
            invalid_sink.records[0]["error_code"],
            "executor_invalid_model_action",
        )


def _configured_client() -> OpenAIExecutorModelClient:
    with patch.dict(
        "os.environ",
        {
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_BASE_URL": "https://example.test/v1",
            "MODEL": "test-model",
        },
        clear=True,
    ):
        return OpenAIExecutorModelClient()


def _model_input() -> ExecutorModelInput:
    return ExecutorModelInput(
        request=RuntimeRequest(
            user_input="查找东京地点",
            session_id="session_test",
        ),
        prompt_contributions=(PromptContribution("travel", "Use travel tools."),),
        context_contributions=(
            ExecutorContextContribution("Current trip context.", "context://1"),
        ),
        memory_contributions=(
            ExecutorMemoryContribution("Saved preference.", "memory://1"),
        ),
        tool_catalog=_CATALOG,
        observations=(
            ToolObservation(
                step_index=1,
                call_id="previous_call",
                tool_name="travel.search_places",
                status=ToolCallStatus.FAILED,
                error=ToolError("provider_failed", "Safe failure.", True),
            ),
        ),
        step_index=2,
    )


def _function_call(call_id: str, name: str, arguments: dict[str, object]):
    return SimpleNamespace(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=json.dumps(arguments),
    )


def _response(*, output_text: str = "", calls: list[object] | None = None):
    return SimpleNamespace(output=calls or [], output_text=output_text)


class _FakeResponses:
    def __init__(self, response_or_error) -> None:
        self._response_or_error = response_or_error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        if isinstance(self._response_or_error, Exception):
            raise self._response_or_error
        return self._response_or_error


class _FakeOpenAIClient:
    def __init__(self, response_or_error) -> None:
        self.responses = _FakeResponses(response_or_error)


class _RecordingLlmSink:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **record: Any) -> None:
        self.records.append(record)


if __name__ == "__main__":
    unittest.main()
