from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    FETCH_SOURCE_TOOL,
    SAVE_SOURCE_TOOL,
    build_research_tools,
)
from app.intent.models import IntentDecision, IntentType
from app.orchestration.nodes import execute_tool
from app.orchestration.state import create_graph_state
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.models import SkillSelection
from app.tools.calling import OpenAIToolCallSelectionClient
from app.tools.models import ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection


class DirectToolExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        service = ResearchService(
            FixtureResearchSourcePort(
                {
                    "hf-daily": {
                        "title": "HF Daily",
                        "url": "https://huggingface.co/papers",
                        "summary": "Fixture research summary.",
                    }
                }
            ),
            ResearchRepository(self.conn),
        )
        self.registry = ToolRegistry(build_research_tools(service))

    def tearDown(self) -> None:
        self.conn.close()

    def test_model_receives_only_skill_and_policy_filtered_catalog(self) -> None:
        client = RecordingToolCallClient(
            ToolCall("call_fetch", FETCH_SOURCE_TOOL, {"source_key": "hf-daily"})
        )

        state = execute_tool(
            _ready_state(["external_read"]),
            tool_runtime_factory=lambda: ToolRuntime.from_registry(self.registry),
            selection_client=client,
        )

        self.assertEqual([item["name"] for item in client.catalog], [FETCH_SOURCE_TOOL])
        self.assertNotIn(SAVE_SOURCE_TOOL, repr(client.catalog))
        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(state["result"].tool_result["status"], ToolCallStatus.SUCCEEDED)
        self.assertEqual(state["result"].tool_result["output"]["source_key"], "hf-daily")

    def test_gateway_rejects_model_call_not_in_exposed_catalog(self) -> None:
        client = RecordingToolCallClient(
            ToolCall("call_save", SAVE_SOURCE_TOOL, {"observation_id": "hidden"})
        )

        state = execute_tool(
            _ready_state(["external_read"]),
            tool_runtime_factory=lambda: ToolRuntime.from_registry(self.registry),
            selection_client=client,
        )

        self.assertEqual(state["result"].status, RuntimeStatus.UNSUPPORTED)
        self.assertEqual(state["result"].tool_result["status"], ToolCallStatus.DENIED)
        self.assertEqual(state["result"].tool_result["error"]["code"], "tool_not_allowed")


class OpenAIToolCallSelectionClientTest(unittest.TestCase):
    @patch("app.tools.calling.load_dotenv")
    @patch("app.tools.calling.OpenAI")
    def test_responses_call_uses_only_supplied_catalog_and_parses_call(
        self,
        openai_type: Any,
        _load_dotenv: Any,
    ) -> None:
        api = FakeOpenAIClient()
        openai_type.return_value = api
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_BASE_URL": "https://example.test/v1",
                "MODEL": "test-model",
            },
            clear=True,
        ):
            client = OpenAIToolCallSelectionClient()

        call = client.select(
            RuntimeRequest(user_input="Fetch HF papers", session_id="session_test"),
            (),
            (
                {
                    "name": FETCH_SOURCE_TOOL,
                    "description": "Fetch source.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"source_key": {"type": "string"}},
                        "required": ["source_key"],
                        "additionalProperties": False,
                    },
                },
            ),
        )

        self.assertEqual(call.tool_name, FETCH_SOURCE_TOOL)
        self.assertEqual(call.arguments, {"source_key": "hf-daily"})
        request = api.responses.calls[0]
        self.assertEqual(request["max_tool_calls"], 1)
        self.assertFalse(request["parallel_tool_calls"])
        self.assertEqual([item["name"] for item in request["tools"]], [FETCH_SOURCE_TOOL])


class RecordingToolCallClient:
    def __init__(self, call: ToolCall | None) -> None:
        self._call = call
        self.catalog: tuple[dict[str, Any], ...] = ()

    def select(self, request, prompt_contributions, tool_catalog):
        self.catalog = tuple(tool_catalog)
        return self._call


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = SimpleNamespace(
            type="function_call",
            call_id="provider_call_1",
            name=FETCH_SOURCE_TOOL,
            arguments=json.dumps({"source_key": "hf-daily"}),
        )
        return SimpleNamespace(output=[item])


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def _ready_state(allowed_effects: list[str]):
    state = create_graph_state(
        RuntimeRequest(user_input="Fetch HF papers", session_id="session_test")
    )
    state["intent"] = IntentDecision(intent_type=IntentType.READ, confidence=0.9)
    state["policy"] = PolicyDecision(
        action=PolicyAction.ALLOW,
        allowed_effects=allowed_effects,
    )
    state["skill_selection"] = SkillSelection(("research",), "Research applies.")
    return state


if __name__ == "__main__":
    unittest.main()
