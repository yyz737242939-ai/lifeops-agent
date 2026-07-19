from __future__ import annotations

import unittest

from app.intent.models import ClassifierResult, IntentDecision, IntentType
from app.policy.models import PolicyAction
from app.policy.service import PolicyService
from app.runtime.models import RuntimeRequest


class PolicyServiceTest(unittest.TestCase):
    def test_non_write_intents_do_not_produce_write_authorization(self) -> None:
        service = PolicyService()

        for intent_type in (IntentType.CHAT, IntentType.READ, IntentType.PLAN_REQUEST):
            with self.subTest(intent_type=intent_type):
                decision = service.evaluate(
                    _request("帮我规划明天安排"),
                    IntentDecision(intent_type=intent_type, confidence=0.8),
                )

                self.assertEqual(decision.action, PolicyAction.ALLOW)
                expected_effects = (
                    ["read", "external_read"]
                    if intent_type == IntentType.READ
                    else []
                )
                self.assertEqual(decision.allowed_effects, expected_effects)

    def test_explicit_write_request_for_supported_target_is_allowed(self) -> None:
        decision = PolicyService().evaluate(
            _request("把明天跑步加入任务"),
            IntentDecision(
                intent_type=IntentType.WRITE_REQUEST,
                confidence=0.9,
                write_candidate=True,
            ),
        )

        self.assertEqual(decision.action, PolicyAction.ALLOW)
        self.assertEqual(decision.allowed_effects, ["write"])

    def test_write_request_without_supported_object_requires_confirmation(self) -> None:
        decision = PolicyService().evaluate(
            _request("帮我记录一下"),
            IntentDecision(
                intent_type=IntentType.WRITE_REQUEST,
                confidence=0.7,
                write_candidate=True,
            ),
        )

        self.assertEqual(decision.action, PolicyAction.REQUIRES_CONFIRMATION)
        self.assertTrue(decision.requires_confirmation)

    def test_unknown_intent_does_not_allow(self) -> None:
        decision = PolicyService().evaluate(
            _request("???"),
            IntentDecision(intent_type=IntentType.UNSUPPORTED, confidence=0.1),
        )

        self.assertEqual(decision.action, PolicyAction.DENY)

    def test_llm_classifier_result_cannot_authorize_write(self) -> None:
        decision = PolicyService().evaluate(
            _request("帮我记录一下"),
            IntentDecision(
                intent_type=IntentType.CLARIFICATION_NEEDED,
                confidence=0.0,
                classifier_results=[
                    ClassifierResult(
                        classifier_name="llm",
                        status="matched",
                        intent_type=IntentType.WRITE_REQUEST,
                        confidence=0.99,
                    )
                ],
            ),
        )

        self.assertEqual(decision.action, PolicyAction.REQUIRES_CONFIRMATION)

    def test_metadata_cannot_bypass_policy(self) -> None:
        with self.assertRaises(TypeError):
            RuntimeRequest(
                user_input="帮我规划明天安排",
                session_id="session_test",
                metadata={"planner": {"write_authorized": True}},
            )


def _request(user_input: str) -> RuntimeRequest:
    return RuntimeRequest(user_input=user_input, session_id="session_test")


if __name__ == "__main__":
    unittest.main()
