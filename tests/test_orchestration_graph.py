from __future__ import annotations

import unittest

from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator, build_runtime_graph
from app.orchestration.state import create_graph_state
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from tests.helpers import create_test_skill_service


class OrchestrationGraphTest(unittest.TestCase):
    def test_semantic_events_follow_each_real_service_call(self) -> None:
        timeline: list[tuple[str, str]] = []
        sink = TimelineTraceSink(timeline)
        orchestrator = RuntimeOrchestrator(
            create_test_skill_service(),
            intent_service=TimelineIntentService(timeline),
            policy_service=TimelinePolicyService(timeline),
        )

        orchestrator.invoke(_request(), trace=sink)

        self.assertLess(
            timeline.index(("call", "intent")),
            timeline.index(("event", "intent.classified")),
        )
        self.assertLess(
            timeline.index(("event", "intent.classified")),
            timeline.index(("call", "policy")),
        )
        self.assertLess(
            timeline.index(("call", "policy")),
            timeline.index(("event", "policy.decided")),
        )

    def test_invoke_trace_never_persists_raw_user_input(self) -> None:
        secret = "private-user-input-9384"
        sink = RecordingTraceSink()
        orchestrator = RuntimeOrchestrator(
            create_test_skill_service(),
            intent_service=FixedIntentService(IntentType.CHAT),
            policy_service=FixedPolicyService(PolicyAction.ALLOW),
        )

        orchestrator.invoke(
            RuntimeRequest(user_input=secret, session_id="session_test"),
            trace=sink,
        )

        self.assertNotIn(secret, repr(sink.events))

    def test_allow_route_runs_direct_executor_then_finalize(self) -> None:
        state = _invoke(IntentType.WRITE_REQUEST, PolicyAction.ALLOW)

        self.assertEqual(
            state["graph_path"],
            [
                "classify_intent",
                "decide_policy",
                "prepare_skills",
                "execute_tool",
                "finalize",
            ],
        )
        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(
            state["result"].trace_summary,
            ["runtime.tool_catalog.empty"],
        )

    def test_confirmation_route_does_not_use_interrupt(self) -> None:
        state = _invoke(
            IntentType.CLARIFICATION_NEEDED,
            PolicyAction.REQUIRES_CONFIRMATION,
        )

        self.assertEqual(
            state["graph_path"],
            [
                "classify_intent",
                "decide_policy",
                "requires_confirmation",
                "finalize",
            ],
        )
        self.assertEqual(state["result"].status, RuntimeStatus.REQUIRES_CONFIRMATION)

    def test_deny_route_runs_deny_then_finalize(self) -> None:
        state = _invoke(IntentType.UNSUPPORTED, PolicyAction.DENY)

        self.assertEqual(
            state["graph_path"],
            ["classify_intent", "decide_policy", "deny", "finalize"],
        )
        self.assertEqual(state["result"].status, RuntimeStatus.UNSUPPORTED)

    def test_intent_failure_ends_graph_before_policy(self) -> None:
        policy_service = RecordingPolicyService(PolicyAction.ALLOW)
        sink = RecordingTraceSink()
        orchestrator = RuntimeOrchestrator(
            create_test_skill_service(),
            intent_service=FailingIntentService(),
            policy_service=policy_service,
        )

        state = orchestrator.invoke(_request(), trace=sink)

        self.assertEqual(state["graph_path"], ["classify_intent"])
        self.assertEqual(state["result"].error_code, "runtime.intent_failed")
        self.assertFalse(policy_service.called)
        self.assertEqual(sink.events[0][0], "intent.failed")

    def test_policy_failure_ends_graph_before_execution(self) -> None:
        sink = RecordingTraceSink()
        orchestrator = RuntimeOrchestrator(
            create_test_skill_service(),
            intent_service=FixedIntentService(IntentType.CHAT),
            policy_service=FailingPolicyService(),
        )

        state = orchestrator.invoke(_request(), trace=sink)

        self.assertEqual(state["graph_path"], ["classify_intent", "decide_policy"])
        self.assertEqual(state["result"].error_code, "runtime.policy_failed")
        self.assertEqual(
            [event_type for event_type, _ in sink.events],
            ["intent.classified", "policy.failed"],
        )

    def test_runtime_orchestrator_handle_returns_graph_result(self) -> None:
        result = RuntimeOrchestrator(
            create_test_skill_service(),
            intent_service=FixedIntentService(IntentType.WRITE_REQUEST),
            policy_service=FixedPolicyService(PolicyAction.ALLOW),
        ).handle(_request())

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertIn("No authorized Tool", result.message)


def _invoke(intent_type: IntentType, action: PolicyAction):
    graph = build_runtime_graph(
        FixedIntentService(intent_type),
        FixedPolicyService(action),
        create_test_skill_service(),
    )
    return graph.invoke(create_graph_state(_request()))


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
    def __init__(self, action: PolicyAction) -> None:
        super().__init__(action)
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


class RecordingTraceSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict | None]] = []

    def append(self, event_type: str, payload: dict | None = None) -> None:
        self.events.append((event_type, payload))


class TimelineTraceSink:
    def __init__(self, timeline: list[tuple[str, str]]) -> None:
        self._timeline = timeline

    def append(self, event_type: str, payload: dict | None = None) -> None:
        self._timeline.append(("event", event_type))


class TimelineIntentService:
    def __init__(self, timeline: list[tuple[str, str]]) -> None:
        self._timeline = timeline

    def classify(self, request: RuntimeRequest) -> IntentDecision:
        self._timeline.append(("call", "intent"))
        return IntentDecision(intent_type=IntentType.CHAT, confidence=0.8)


class TimelinePolicyService:
    def __init__(self, timeline: list[tuple[str, str]]) -> None:
        self._timeline = timeline

    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        self._timeline.append(("call", "policy"))
        return PolicyDecision(action=PolicyAction.ALLOW)


def _request() -> RuntimeRequest:
    return RuntimeRequest(user_input="test input", session_id="session_test")


if __name__ == "__main__":
    unittest.main()
