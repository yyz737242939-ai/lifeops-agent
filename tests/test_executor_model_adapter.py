from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.executor.errors import ExecutorModelError, InvalidExecutorModelActionError
from app.executor.model_adapter import (
    EXECUTOR_SYSTEM_PROMPT,
    OpenAIExecutorModelClient,
)
from app.executor.models import (
    ExecutorContextContribution,
    ExecutorMemoryContribution,
    ExecutorModelInput,
    FinalAnswerActionClaim,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    PlanStepDependencyResult,
    PlanStepExecutionInput,
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
    def test_prompt_requires_claim_for_successful_observation_used_in_answer(self) -> None:
        self.assertIn(
            "each successful call whose result is\n  used or described by the answer",
            EXECUTOR_SYSTEM_PROMPT,
        )
        self.assertIn(
            "all\n  observed Tool actions failed",
            EXECUTOR_SYSTEM_PROMPT,
        )
        self.assertIn(
            "evidence reference or use an observation id",
            EXECUTOR_SYSTEM_PROMPT,
        )
        self.assertIn(
            "successful READ with no non-null\n  evidence reference",
            EXECUTOR_SYSTEM_PROMPT,
        )

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
        self.assertEqual(
            [item["name"] for item in call["tools"]],
            ["travel.search_places", "lifeops_submit_final_answer"],
        )
        self.assertNotIn("previous_response_id", call)
        self.assertTrue(call["instructions"].startswith(EXECUTOR_SYSTEM_PROMPT))
        self.assertIn("Do not also emit a", call["instructions"])
        self.assertIn("Tool Observations as the source of truth", call["instructions"])
        self.assertIn(
            "Context and Memory contributions before choosing a tool",
            call["instructions"],
        )
        self.assertIn("Never call a Memory tool to look up a Profile fact", call["instructions"])
        self.assertIn("After a successful WRITE observation", call["instructions"])
        self.assertIn("failed with `retryable: false`", call["instructions"])
        self.assertIn("current user request explicitly asks", call["instructions"])
        self.assertIn("Selected Skill instructions:\nUse travel tools.", call["instructions"])
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
    def test_structured_final_answer_preserves_action_claims(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        openai_type.return_value = _FakeOpenAIClient(
            _response(
                calls=[
                    _function_call(
                        "final_1",
                        "lifeops_submit_final_answer",
                        {
                            "message": "已保存。",
                            "execution_claims": [
                                {
                                    "claim_id": "claim_1",
                                    "call_id": "call_1",
                                    "evidence_refs": ["source/ref_1"],
                                }
                            ],
                        },
                    )
                ]
            )
        )

        decision = _configured_client().decide(_model_input())

        self.assertEqual(
            decision,
            FinalAnswerDecision(
                "已保存。",
                (
                    FinalAnswerActionClaim(
                        "claim_1", "call_1", ("source/ref_1",)
                    ),
                ),
            ),
        )

    @patch("app.executor.model_adapter.load_dotenv")
    @patch("app.executor.model_adapter.OpenAI")
    def test_invalid_provider_actions_fail_closed(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        cases = (
            _response(),
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
    def test_single_function_call_owns_decision_when_provider_adds_progress_text(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        openai_type.return_value = _FakeOpenAIClient(
            _response(
                output_text="正在查询地点。",
                calls=[
                    _function_call(
                        "call_1", "travel.search_places", {"query": "Tokyo"}
                    )
                ],
            )
        )

        decision = _configured_client().decide(_model_input())

        self.assertIsInstance(decision, ToolActionDecision)
        self.assertEqual(decision.call.tool_name, "travel.search_places")
        self.assertEqual(decision.call.arguments, {"query": "Tokyo"})

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

    @patch("app.executor.model_adapter.load_dotenv")
    @patch("app.executor.model_adapter.OpenAI")
    def test_plan_step_can_report_goal_not_achieved_but_direct_cannot(
        self, openai_type: Any, _load_dotenv: Any
    ) -> None:
        response = _response(
            calls=[
                _function_call(
                    "control_1", "report_goal_not_achieved", {"reason_code": "missing_scope"}
                )
            ]
        )
        api = _FakeOpenAIClient(response)
        openai_type.return_value = api
        decision = _configured_client().decide(_model_input(plan_step=_plan_step_input()))

        self.assertEqual(decision, GoalNotAchievedDecision("missing_scope"))
        call = api.responses.calls[0]
        self.assertEqual(call["tools"][-1]["name"], "report_goal_not_achieved")
        payload = json.loads(call["input"])
        self.assertEqual(payload["plan_step"]["current_objective"], "形成摘要")
        self.assertEqual(payload["plan_step"]["dependency_results"][0]["step_id"], "read")

        openai_type.return_value = _FakeOpenAIClient(response)
        with self.assertRaises(InvalidExecutorModelActionError):
            _configured_client().decide(_model_input())


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


def _model_input(
    *,
    plan_step: PlanStepExecutionInput | None = None,
) -> ExecutorModelInput:
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
        plan_step=plan_step,
    )


def _plan_step_input() -> PlanStepExecutionInput:
    return PlanStepExecutionInput(
        "plan_1",
        1,
        "write",
        "完成研究",
        "形成摘要",
        "得到摘要",
        (PlanStepDependencyResult("read", "读取完成。"),),
        3,
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
