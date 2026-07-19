from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.loader import discover_skills
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService


class OrchestrationSkillStageTest(unittest.TestCase):
    def test_allow_route_selects_loads_and_builds_prompt_contributions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = self._registry(Path(tmpdir))
            client = FixedSelectionClient(["travel", "research"])
            trace = RecordingTraceSink()
            orchestrator = RuntimeOrchestrator(
                intent_service=FixedIntentService(IntentType.PLAN_REQUEST),
                policy_service=FixedPolicyService(PolicyAction.ALLOW),
                skill_service=SkillService(registry, client),
            )

            state = orchestrator.invoke(_request(), trace=trace)

        self.assertEqual(
            state["graph_path"],
            [
                "classify_intent",
                "decide_policy",
                "prepare_skills",
                "execute_executor",
                "finalize",
            ],
        )
        self.assertEqual(state["skill_selection"].selected_skill_ids, ("travel", "research"))
        self.assertEqual(
            [item.skill_id for item in state["prompt_contributions"]],
            ["travel", "research"],
        )
        self.assertEqual(tuple(item.skill_id for item in client.received_metadata), ("research", "travel"))
        self.assertEqual(
            [event_type for event_type, _ in trace.events],
            [
                "intent.classified",
                "policy.decided",
                "orchestration.route.selected",
                "skill.selected",
                "skill.loaded",
                "skill.loaded",
                "tool.catalog.resolved",
                "executor.action.selected",
                "executor.stopped",
            ],
        )

    def test_skill_selection_failure_stops_before_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trace = RecordingTraceSink()
            orchestrator = RuntimeOrchestrator(
                intent_service=FixedIntentService(IntentType.CHAT),
                policy_service=FixedPolicyService(PolicyAction.ALLOW),
                skill_service=SkillService(
                    self._registry(Path(tmpdir)),
                    FailingSelectionClient(),
                ),
            )

            state = orchestrator.invoke(_request(), trace=trace)

        self.assertEqual(
            state["graph_path"],
            ["classify_intent", "decide_policy", "prepare_skills"],
        )
        self.assertEqual(state["result"].status, RuntimeStatus.ERROR)
        self.assertEqual(state["result"].error_code, "runtime.skill_failed")
        self.assertEqual(state["error_stage"], "skill")
        self.assertNotIn("execute_executor", state["graph_path"])
        self.assertEqual(trace.events[-1][0], "skill.selection.failed")

    def test_confirmation_and_deny_routes_do_not_call_skill_selector(self) -> None:
        for action in (PolicyAction.REQUIRES_CONFIRMATION, PolicyAction.DENY):
            with self.subTest(action=action):
                client = RecordingSelectionClient()
                orchestrator = RuntimeOrchestrator(
                    intent_service=FixedIntentService(IntentType.CHAT),
                    policy_service=FixedPolicyService(action),
                    skill_service=SkillService(SkillRegistry(), client),
                )

                state = orchestrator.invoke(_request())

                self.assertFalse(client.called)
                self.assertNotIn("prepare_skills", state["graph_path"])

    @staticmethod
    def _registry(root: Path) -> SkillRegistry:
        for skill_id in ("research", "travel"):
            skill_dir = root / skill_id
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                f"name: {skill_id}\n"
                f"description: {skill_id} description.\n"
                "---\n"
                f"# {skill_id} instructions",
                encoding="utf-8",
            )
        return SkillRegistry(discover_skills(root))


class FixedSelectionClient:
    def __init__(self, selected_ids: list[str]) -> None:
        self._selected_ids = selected_ids
        self.received_metadata: tuple[SkillDefinition, ...] = ()

    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        self.received_metadata = skill_metadata
        return {"selected_skill_ids": self._selected_ids, "reason": "Relevant Skills."}


class FailingSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


class RecordingSelectionClient:
    def __init__(self) -> None:
        self.called = False

    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        self.called = True
        return {"selected_skill_ids": [], "reason": "No Skill applies."}


class FixedIntentService:
    def __init__(self, intent_type: IntentType) -> None:
        self._intent_type = intent_type

    def classify(self, request: RuntimeRequest) -> IntentDecision:
        return IntentDecision(intent_type=self._intent_type, confidence=0.8)


class FixedPolicyService:
    def __init__(self, action: PolicyAction) -> None:
        self._action = action

    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        return PolicyDecision(
            action=self._action,
            requires_confirmation=self._action == PolicyAction.REQUIRES_CONFIRMATION,
        )


class RecordingTraceSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any] | None]] = []

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, payload))


def _request() -> RuntimeRequest:
    return RuntimeRequest(user_input="Research a trip.", session_id="session_test")


if __name__ == "__main__":
    unittest.main()
