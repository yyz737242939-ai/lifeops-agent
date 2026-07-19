from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import Any

from app.executor.models import ExecutorModelInput, FinalAnswerDecision, ToolActionDecision
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.bootstrap import _build_tool_runtime
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.loader import discover_skills
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.tools.models import ToolCall, ToolCallStatus
from tests.helpers import create_test_connection


@unittest.skipUnless(
    os.environ.get("LIFEOPS_RUN_LIVE_HF_SMOKE") == "1",
    "Set LIFEOPS_RUN_LIVE_HF_SMOKE=1 to call the public Hugging Face API.",
)
class ResearchMcpLiveSmokeTest(unittest.TestCase):
    def test_runtime_searches_public_hugging_face_through_real_mcp(self) -> None:
        conn = create_test_connection()
        try:
            model = _LiveSearchModel()
            runtime = _build_tool_runtime(conn, Path("app/skills"))
            orchestrator = RuntimeOrchestrator(
                skill_service=SkillService(
                    SkillRegistry(discover_skills(Path("app/skills"))),
                    _ResearchSkillSelectionClient(),
                ),
                intent_service=_ReadIntentService(),
                policy_service=_ExternalReadPolicyService(),
                execution_scope_factory=lambda: runtime,
                executor=ReactExecutor(model),
            )

            state = orchestrator.invoke(
                RuntimeRequest(
                    user_input="Search public Hugging Face papers about agents.",
                    session_id="session_research_mcp_live_smoke",
                ),
                trace=_RecordingTraceSink(),
            )

            self.assertEqual(state["result"].status, RuntimeStatus.OK)
            observation = model.inputs[-1].observations[0]
            if observation.status is ToolCallStatus.FAILED:
                code = observation.error.code if observation.error else "unknown"
                category = (
                    "provider"
                    if code.startswith("research_paper_provider")
                    or code == "research_paper_rate_limited"
                    else "lifeops_contract"
                )
                self.fail(f"live_smoke_{category}_failure:{code}")
            papers = observation.output["observations"]
            self.assertGreater(len(papers), 0)
            self.assertLessEqual(len(papers), 3)
            for paper in papers:
                self.assertEqual(paper["source_key"], "hf_paper")
                self.assertTrue(
                    paper["url"].startswith("https://huggingface.co/papers/")
                )
                self.assertTrue(paper["provenance"].startswith("external:mcp:"))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
                0,
            )
        finally:
            conn.close()


class _LiveSearchModel:
    def __init__(self) -> None:
        self.inputs: list[ExecutorModelInput] = []

    def decide(self, model_input: ExecutorModelInput):
        self.inputs.append(model_input)
        if model_input.observations:
            return FinalAnswerDecision("Live Hugging Face search completed.")
        return ToolActionDecision(
            ToolCall(
                "live_hf_search",
                "research.search_papers",
                {"query": "agent", "limit": 3},
            )
        )


class _ResearchSkillSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        del request, skill_metadata
        return {"selected_skill_ids": ["research"], "reason": "live smoke"}


class _ReadIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        del request
        return IntentDecision(IntentType.READ, 1.0)


class _ExternalReadPolicyService:
    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        del request, intent
        return PolicyDecision(
            PolicyAction.ALLOW,
            allowed_effects=["external_read"],
        )


class _RecordingTraceSink:
    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        del event_type, payload


if __name__ == "__main__":
    unittest.main()
