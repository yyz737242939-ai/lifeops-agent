from __future__ import annotations

import unittest

from app.intent.classifiers import LlmIntentClassifier
from app.intent.models import ClassifierResult, IntentType
from app.intent.service import IntentService
from app.runtime.models import RuntimeRequest


class IntentServiceTest(unittest.TestCase):
    def test_plan_keyword_in_plain_statement_does_not_trigger_plan_request(self) -> None:
        decision = IntentService().classify(_request("我计划明天跑步"))

        self.assertEqual(decision.intent_type, IntentType.CHAT)
        self.assertFalse(decision.write_candidate)

    def test_planning_request_returns_plan_request(self) -> None:
        decision = IntentService().classify(_request("帮我规划明天的安排"))

        self.assertEqual(decision.intent_type, IntentType.PLAN_REQUEST)
        self.assertFalse(decision.write_candidate)

    def test_write_request_returns_write_candidate(self) -> None:
        decision = IntentService().classify(_request("把明天跑步加入任务"))

        self.assertEqual(decision.intent_type, IntentType.WRITE_REQUEST)
        self.assertTrue(decision.write_candidate)

    def test_update_and_archive_of_supported_objects_are_write_requests(self) -> None:
        for user_input in (
            "Call memory.update exactly once for this memory.",
            "Call memory.archive exactly once for this memory.",
            "更新这条记忆",
            "归档这条记忆",
        ):
            with self.subTest(user_input=user_input):
                decision = IntentService().classify(_request(user_input))

                self.assertEqual(decision.intent_type, IntentType.WRITE_REQUEST)
                self.assertTrue(decision.write_candidate)

    def test_bare_planning_keyword_requires_clarification(self) -> None:
        decision = IntentService().classify(_request("计划一下"))

        self.assertEqual(decision.intent_type, IntentType.CLARIFICATION_NEEDED)
        self.assertTrue(decision.needs_clarification)
        self.assertFalse(decision.write_candidate)

    def test_intent_service_calls_rule_and_llm_classifiers(self) -> None:
        decision = IntentService().classify(_request("列出今天任务"))

        self.assertEqual(
            [result.classifier_name for result in decision.classifier_results],
            ["rule_based", "llm"],
        )

    def test_llm_intent_classifier_placeholder_does_not_call_model(self) -> None:
        result = LlmIntentClassifier().classify(_request("帮我规划明天的安排"))

        self.assertEqual(
            result,
            ClassifierResult(
                classifier_name="llm",
                status="not_available",
                intent_type=IntentType.CLARIFICATION_NEEDED,
                confidence=0.0,
                reason="LLM intent classifier is not wired yet.",
            ),
        )


def _request(user_input: str) -> RuntimeRequest:
    return RuntimeRequest(user_input=user_input, session_id="session_test")


if __name__ == "__main__":
    unittest.main()
