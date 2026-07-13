from __future__ import annotations

import inspect
import unittest

from app.intent.models import IntentDecision, IntentType
from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
)
from app.orchestration.graph import RuntimeOrchestrator
from app.orchestration.nodes import execute_executor
from app.orchestration.state import GraphState, create_graph_state
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.runtime.service import RuntimeService
from app.skills.models import SkillSelection
from app.tools.models import AllowedToolSet
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_skill_service


class ExecutorRuntimeIntegrationTest(unittest.TestCase):
    def test_outer_node_passes_fixed_authorization_and_maps_final_result(self) -> None:
        executor = RecordingExecutor(_executor_result())
        state = _ready_state()
        runtime = ToolRuntime.from_registry(ToolRegistry())

        updated = execute_executor(
            state,
            executor=executor,
            execution_scope=runtime,
        )

        self.assertEqual(updated["result"].status, RuntimeStatus.OK)
        self.assertEqual(updated["result"].message, "最终回答。")
        self.assertEqual(updated["graph_path"][-1], "execute_executor")
        self.assertEqual(executor.allowed_tools, AllowedToolSet())
        self.assertIs(executor.execution_scope, runtime)

    def test_executor_stop_reasons_map_to_existing_runtime_statuses(self) -> None:
        cases = (
            (
                ExecutorStatus.STOPPED,
                ExecutorStopReason.CONFIRMATION_REQUIRED,
                RuntimeStatus.REQUIRES_CONFIRMATION,
            ),
            (
                ExecutorStatus.STOPPED,
                ExecutorStopReason.SAFETY_DENIED,
                RuntimeStatus.UNSUPPORTED,
            ),
            (
                ExecutorStatus.STOPPED,
                ExecutorStopReason.LIMIT_REACHED,
                RuntimeStatus.ERROR,
            ),
            (
                ExecutorStatus.FAILED,
                ExecutorStopReason.MODEL_FAILED,
                RuntimeStatus.ERROR,
            ),
        )
        for status, stop_reason, runtime_status in cases:
            with self.subTest(stop_reason=stop_reason):
                result = ExecutorResult(
                    run_id="run_test",
                    status=status,
                    stop_reason=stop_reason,
                    final_message=None,
                    step_count=1,
                    error_code=(
                        "executor_model_failed"
                        if status == ExecutorStatus.FAILED
                        else None
                    ),
                )
                updated = execute_executor(
                    _ready_state(),
                    executor=RecordingExecutor(result),
                    execution_scope=ToolRuntime.from_registry(ToolRegistry()),
                )
                self.assertEqual(updated["result"].status, runtime_status)

    def test_outer_routes_invoke_executor_only_for_policy_allow(self) -> None:
        for action, expected_calls in (
            (PolicyAction.ALLOW, 1),
            (PolicyAction.REQUIRES_CONFIRMATION, 0),
            (PolicyAction.DENY, 0),
        ):
            with self.subTest(action=action):
                executor = RecordingExecutor(_executor_result())
                orchestrator = RuntimeOrchestrator(
                    create_test_skill_service(),
                    executor=executor,
                    intent_service=_FixedIntentService(),
                    policy_service=_FixedPolicyService(action),
                )

                state = orchestrator.invoke(_request())

                self.assertEqual(executor.calls, expected_calls)
                self.assertNotIn("executor_state", GraphState.__annotations__)
                self.assertNotIn("observations", GraphState.__annotations__)

    def test_runtime_service_no_longer_accepts_direct_tool_selection_client(self) -> None:
        parameters = inspect.signature(RuntimeService.__init__).parameters

        self.assertIn("executor", parameters)
        self.assertNotIn("tool_call_selection_client", parameters)


class RecordingExecutor:
    def __init__(self, result: ExecutorResult) -> None:
        self._result = result
        self.calls = 0
        self.allowed_tools = None
        self.execution_scope = None

    def execute(
        self,
        request,
        prompt_contributions,
        allowed_tools,
        execution_scope,
        trace=None,
    ) -> ExecutorResult:
        self.calls += 1
        self.allowed_tools = allowed_tools
        self.execution_scope = execution_scope
        return self._result


def _ready_state():
    state = create_graph_state(_request())
    state["intent"] = IntentDecision(intent_type=IntentType.CHAT, confidence=0.9)
    state["policy"] = PolicyDecision(
        action=PolicyAction.ALLOW,
        allowed_effects=["read"],
    )
    state["skill_selection"] = SkillSelection((), "No Skill needed.")
    return state


def _executor_result() -> ExecutorResult:
    return ExecutorResult(
        run_id="run_test",
        status=ExecutorStatus.COMPLETED,
        stop_reason=ExecutorStopReason.FINAL_ANSWER,
        final_message="最终回答。",
        step_count=1,
    )


def _request() -> RuntimeRequest:
    return RuntimeRequest(
        user_input="执行请求",
        session_id="session_test",
        run_id="run_test",
    )


class _FixedIntentService:
    def classify(self, request):
        from app.intent.models import IntentDecision, IntentType

        return IntentDecision(intent_type=IntentType.CHAT, confidence=0.9)


class _FixedPolicyService:
    def __init__(self, action: PolicyAction) -> None:
        self._action = action

    def evaluate(self, request, intent):
        return PolicyDecision(
            action=self._action,
            allowed_effects=["read"] if self._action == PolicyAction.ALLOW else [],
            requires_confirmation=self._action == PolicyAction.REQUIRES_CONFIRMATION,
        )


if __name__ == "__main__":
    unittest.main()
