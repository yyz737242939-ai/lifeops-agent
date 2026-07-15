from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    APPEND_REVISION_TOOL,
    CREATE_TOPIC_TOOL,
    LINK_ITEMS_TOOL,
    SAVE_SOURCE_TOOL,
    SEARCH_KNOWLEDGE_TOOL,
    SEARCH_PAPERS_TOOL,
    build_research_tools,
)
from app.executor.models import (
    ExecutionLimits,
    ExecutorModelInput,
    FinalAnswerDecision,
    ToolActionDecision,
)
from app.executor.service import ReactExecutor
from app.integrations.mcp.models import McpServerConfig
from app.integrations.research_mcp.adapter import HuggingFaceMcpPaperSearchAdapter
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.loader import discover_skills
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.tools.models import ConfirmedAction, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection


class ResearchMcpCompiledE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()

    def tearDown(self) -> None:
        self.conn.close()

    def test_real_stdio_search_save_link_revision_and_topic_read(self) -> None:
        model = _MainlineModel()
        confirmations = _ConfirmEveryWrite()

        state = self._invoke(model, confirmation_provider=confirmations)

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        observations = model.inputs[-1].observations
        self.assertEqual(len(observations), 7)
        self.assertEqual(observations[0].tool_name, CREATE_TOPIC_TOOL)
        self.assertEqual(observations[1].tool_name, SEARCH_PAPERS_TOOL)
        self.assertEqual(observations[5].status, ToolCallStatus.FAILED)
        self.assertEqual(observations[6].output["items"][0]["item_kind"], "topic")
        self.assertEqual(self._count("research_topics"), 1)
        self.assertEqual(self._count("research_sources"), 1)
        self.assertEqual(self._count("research_source_snapshots"), 1)
        self.assertEqual(self._count("research_links"), 1)
        self.assertEqual(self._count("research_revisions"), 1)
        self.assertEqual(
            confirmations.tool_names,
            [
                CREATE_TOPIC_TOOL,
                SAVE_SOURCE_TOOL,
                LINK_ITEMS_TOOL,
                APPEND_REVISION_TOOL,
                LINK_ITEMS_TOOL,
            ],
        )

    def test_real_stdio_no_results_finishes_without_writes_or_fabrication(self) -> None:
        model = _OneSearchModel("quantum-zebra-no-match")

        state = self._invoke(model)

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        observation = model.inputs[-1].observations[0]
        self.assertEqual(observation.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(
            observation.output,
            {"observations": [], "invalid_count": 0},
        )
        self.assertEqual(self._count("research_sources"), 0)

    def test_real_stdio_provider_failure_returns_safe_observation_and_zero_writes(self) -> None:
        model = _OneSearchModel("agents")

        state = self._invoke(
            model,
            fixture_error="research_paper_provider_unavailable",
        )

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        observation = model.inputs[-1].observations[0]
        self.assertEqual(observation.status, ToolCallStatus.FAILED)
        self.assertEqual(
            observation.error.code,
            "research_paper_provider_unavailable",
        )
        self.assertNotIn("agents", observation.error.message)
        self.assertEqual(self._count("research_sources"), 0)

    def test_unconfirmed_save_after_real_stdio_search_writes_nothing(self) -> None:
        model = _SearchThenSaveModel()

        state = self._invoke(model)

        self.assertEqual(
            state["result"].status,
            RuntimeStatus.REQUIRES_CONFIRMATION,
        )
        self.assertEqual(self._count("research_sources"), 0)
        self.assertEqual(self._count("research_source_snapshots"), 0)

    def _invoke(
        self,
        model,
        *,
        confirmation_provider=None,
        fixture_error: str | None = None,
    ):
        runtime = self._runtime(fixture_error=fixture_error)
        orchestrator = RuntimeOrchestrator(
            skill_service=SkillService(
                SkillRegistry(discover_skills(Path("app/skills"))),
                _ResearchSkillSelectionClient(),
            ),
            intent_service=_ReadIntentService(),
            policy_service=_ResearchPolicyService(),
            execution_scope_factory=lambda: runtime,
            executor=ReactExecutor(
                model,
                limits=ExecutionLimits(max_steps=10),
                confirmation_provider=confirmation_provider,
            ),
        )
        return orchestrator.invoke(
            RuntimeRequest(
                user_input="Run the offline Research MCP workflow.",
                session_id="session_research_mcp_e2e",
            ),
            trace=_RecordingTraceSink(),
        )

    def _runtime(self, *, fixture_error: str | None) -> ToolRuntime:
        server_args = ["-m", "app.integrations.research_mcp.server"]
        if fixture_error is None:
            server_args.extend(
                [
                    "--fixture",
                    str(Path("tests/fixtures/research/hf_papers.json").resolve()),
                ]
            )
        else:
            server_args.extend(["--fixture-error", fixture_error])
        service = ResearchService(
            FixtureResearchSourcePort({}),
            ResearchRepository(self.conn),
            paper_search_port=HuggingFaceMcpPaperSearchAdapter(
                McpServerConfig(
                    server_id="research-compiled-e2e",
                    command=sys.executable,
                    args=tuple(server_args),
                    cwd=Path.cwd(),
                    timeout_seconds=5.0,
                )
            ),
        )
        return ToolRuntime.from_registry(ToolRegistry(build_research_tools(service)))

    def _count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class _MainlineModel:
    def __init__(self) -> None:
        self.inputs: list[ExecutorModelInput] = []

    def decide(self, model_input: ExecutorModelInput):
        self.inputs.append(model_input)
        observations = model_input.observations
        if not observations:
            return _action(
                "create_topic",
                CREATE_TOPIC_TOOL,
                {"name": "Agent Runtime", "description": "Runtime papers"},
            )
        if len(observations) == 1:
            return _action(
                "search_papers",
                SEARCH_PAPERS_TOOL,
                {"query": "agent", "limit": 3},
            )
        if len(observations) == 2:
            return _action(
                "save_source",
                SAVE_SOURCE_TOOL,
                {
                    "observation_id": observations[1].output["observations"][0][
                        "observation_id"
                    ]
                },
            )
        if len(observations) == 3:
            return _action(
                "link_source",
                LINK_ITEMS_TOOL,
                {
                    "from_kind": "source",
                    "from_id": observations[2].output["source_id"],
                    "to_kind": "topic",
                    "to_id": observations[0].output["topic_id"],
                    "relation": "belongs_to",
                },
            )
        if len(observations) == 4:
            return _action(
                "append_revision",
                APPEND_REVISION_TOOL,
                {
                    "item_kind": "source",
                    "item_id": observations[2].output["source_id"],
                    "content": "Reviewed paper source.",
                },
            )
        if len(observations) == 5:
            return _action(
                "duplicate_link",
                LINK_ITEMS_TOOL,
                {
                    "from_kind": "source",
                    "from_id": observations[2].output["source_id"],
                    "to_kind": "topic",
                    "to_id": observations[0].output["topic_id"],
                    "relation": "belongs_to",
                },
            )
        if len(observations) == 6:
            return _action(
                "list_topics",
                SEARCH_KNOWLEDGE_TOOL,
                {"topic_filter": "Agent", "limit": 10, "offset": 0},
            )
        return FinalAnswerDecision("Research MCP workflow completed.")


class _OneSearchModel:
    def __init__(self, query: str) -> None:
        self.query = query
        self.inputs: list[ExecutorModelInput] = []

    def decide(self, model_input: ExecutorModelInput):
        self.inputs.append(model_input)
        if model_input.observations:
            return FinalAnswerDecision("Search completed safely.")
        return _action(
            "search_once",
            SEARCH_PAPERS_TOOL,
            {"query": self.query, "limit": 3},
        )


class _SearchThenSaveModel:
    def __init__(self) -> None:
        self.inputs: list[ExecutorModelInput] = []

    def decide(self, model_input: ExecutorModelInput):
        self.inputs.append(model_input)
        if not model_input.observations:
            return _action(
                "search_before_save",
                SEARCH_PAPERS_TOOL,
                {"query": "agent", "limit": 3},
            )
        return _action(
            "unconfirmed_save",
            SAVE_SOURCE_TOOL,
            {
                "observation_id": model_input.observations[0].output[
                    "observations"
                ][0]["observation_id"]
            },
        )


class _ResearchSkillSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        del request, skill_metadata
        return {"selected_skill_ids": ["research"], "reason": "fixture"}


class _ReadIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        del request
        return IntentDecision(IntentType.READ, 1.0)


class _ResearchPolicyService:
    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        del request, intent
        return PolicyDecision(
            PolicyAction.ALLOW,
            allowed_effects=["read", "external_read", "write"],
        )


class _ConfirmEveryWrite:
    def __init__(self) -> None:
        self.tool_names: list[str] = []

    def confirm(self, run_id, call, tool_definition):
        del tool_definition
        self.tool_names.append(call.tool_name)
        return ConfirmedAction.for_call(
            run_id,
            call,
            expires_at="2100-01-01T00:00:00+00:00",
        )


class _RecordingTraceSink:
    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        del event_type, payload


def _action(call_id: str, tool_name: str, arguments: dict[str, Any]):
    return ToolActionDecision(ToolCall(call_id, tool_name, arguments))


if __name__ == "__main__":
    unittest.main()
