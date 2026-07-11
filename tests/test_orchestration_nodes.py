from __future__ import annotations

import unittest

from app.intent.models import IntentDecision, IntentType
from app.orchestration.nodes import (
    classify_intent,
    decide_policy,
    deny,
    finalize,
    prepare_skills,
    require_confirmation,
    stub_execute,
)
from app.orchestration.state import GraphRoute, create_graph_state
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.runtime.service import RuntimeService
from tests.helpers import create_test_skill_service


class OrchestrationNodesTest(unittest.TestCase):
    def test_node_chain_matches_existing_runtime_result_semantics(self) -> None:
        cases = (
            (IntentType.WRITE_REQUEST, PolicyAction.ALLOW, stub_execute),
            (
                IntentType.CLARIFICATION_NEEDED,
                PolicyAction.REQUIRES_CONFIRMATION,
                require_confirmation,
            ),
            (IntentType.UNSUPPORTED, PolicyAction.DENY, deny),
        )

        for intent_type, policy_action, result_node in cases:
            with self.subTest(policy_action=policy_action):
                intent_service = FixedIntentService(intent_type)
                policy_service = FixedPolicyService(policy_action)
                request = _request("test input")
                expected = RuntimeService(
                    create_test_skill_service(),
                    intent_service=intent_service,
                    policy_service=policy_service,
                ).handle(request)

                state = create_graph_state(request)
                state = classify_intent(state, intent_service)
                state = decide_policy(state, policy_service)
                state = result_node(state)
                state = finalize(state)

                self.assertEqual(state["result"], expected)

    def test_allow_nodes_preserve_stubbed_runtime_result(self) -> None:
        state = create_graph_state(_request("把明天跑步加入任务"))

        state = classify_intent(state, FixedIntentService(IntentType.WRITE_REQUEST))
        state = decide_policy(state, FixedPolicyService(PolicyAction.ALLOW))
        state = prepare_skills(
            state,
            skill_service=create_test_skill_service(),
        )
        state = stub_execute(state)
        state = finalize(state)

        self.assertEqual(state["route"], GraphRoute.ALLOW)
        self.assertEqual(
            state["graph_path"],
            [
                "classify_intent",
                "decide_policy",
                "prepare_skills",
                "stub_execute",
                "finalize",
            ],
        )
        self.assertEqual(state["skill_selection"].selected_skill_ids, ())
        self.assertEqual(state["prompt_contributions"], [])
        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(
            state["result"].trace_summary,
            ["runtime.orchestration.stubbed"],
        )
        self.assertIn("execution is not implemented yet", state["result"].message)

    def test_confirmation_node_does_not_claim_write(self) -> None:
        state = create_graph_state(_request("计划一下"))
        state = classify_intent(
            state,
            FixedIntentService(IntentType.CLARIFICATION_NEEDED),
        )
        state = decide_policy(
            state,
            FixedPolicyService(PolicyAction.REQUIRES_CONFIRMATION),
        )
        state = require_confirmation(state)
        state = finalize(state)

        self.assertEqual(state["route"], GraphRoute.REQUIRES_CONFIRMATION)
        self.assertEqual(state["result"].status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertNotIn("已写入", state["result"].message)

    def test_deny_node_preserves_unsupported_result(self) -> None:
        state = create_graph_state(_request("???"))
        state = classify_intent(state, FixedIntentService(IntentType.UNSUPPORTED))
        state = decide_policy(state, FixedPolicyService(PolicyAction.DENY))
        state = deny(state)
        state = finalize(state)

        self.assertEqual(state["route"], GraphRoute.DENY)
        self.assertEqual(state["result"].status, RuntimeStatus.UNSUPPORTED)

    def test_intent_failure_stops_before_policy(self) -> None:
        policy = RecordingPolicyService()
        state = create_graph_state(_request("hello"))

        state = classify_intent(state, FailingIntentService())

        self.assertEqual(state["error_code"], "runtime.intent_failed")
        self.assertEqual(state["graph_path"], ["classify_intent"])
        self.assertEqual(state["result"].status, RuntimeStatus.ERROR)
        self.assertFalse(policy.called)

    def test_policy_failure_keeps_intent_summary(self) -> None:
        state = create_graph_state(_request("hello"))
        state = classify_intent(state, FixedIntentService(IntentType.CHAT))

        state = decide_policy(state, FailingPolicyService())

        self.assertEqual(state["error_code"], "runtime.policy_failed")
        self.assertEqual(state["graph_path"], ["classify_intent", "decide_policy"])
        self.assertEqual(state["result"].intent["intent_type"], "chat")
        self.assertIsNone(state["result"].policy)


class FixedIntentService:
    def __init__(self, intent_type: IntentType) -> None:
        self._intent_type = intent_type

    def classify(self, request: RuntimeRequest) -> IntentDecision:
        return IntentDecision(
            intent_type=self._intent_type,
            confidence=0.8,
            needs_clarification=self._intent_type == IntentType.CLARIFICATION_NEEDED,
            write_candidate=self._intent_type == IntentType.WRITE_REQUEST,
        )


class FailingIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        raise RuntimeError("boom")


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


class RecordingPolicyService(FixedPolicyService):
    def __init__(self) -> None:
        super().__init__(PolicyAction.ALLOW)
        self.called = False

    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        self.called = True
        return super().evaluate(request, intent)


class FailingPolicyService:
    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        raise RuntimeError("boom")


def _request(user_input: str) -> RuntimeRequest:
    return RuntimeRequest(user_input=user_input, session_id="session_test")


if __name__ == "__main__":
    unittest.main()
