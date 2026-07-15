from __future__ import annotations

import unittest

from app.executor.models import ExecutorResult, ExecutorStatus, ExecutorStopReason
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.planning.controller import PlanController
from app.planning.finalizer import FakePlanFinalizerClient
from app.planning.models import (
    DirectRoute,
    NeedUserRoute,
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerOutput,
    PlanRoute,
    PlanStepDraft,
    PlanningLimits,
)
from app.planning.planner import FakePlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.planning.router import FakePlanningRouteClient
from app.planning.service import PlanningService
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection, create_test_skill_service
from main import _parse_plan_command


class PlanningRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repo = SqlitePlanRepository(self.conn)
        self.limits = PlanningLimits(max_plan_steps=3)

    def tearDown(self) -> None:
        self.conn.close()

    def test_direct_route_preserves_react_path(self) -> None:
        orchestrator = self._orchestrator(
            FakePlanningRouteClient(DirectRoute("single_goal")),
            FakePlannerModelClient(),
            _Executor(),
        )
        state = orchestrator.invoke(_request())

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(
            state["graph_path"],
            [
                "classify_intent",
                "decide_policy",
                "prepare_skills",
                "route_planning",
                "execute_executor",
                "finalize",
            ],
        )

    def test_plan_route_returns_preview_without_executor_call(self) -> None:
        executor = _Executor()
        trace = _Trace()
        orchestrator = self._orchestrator(
            FakePlanningRouteClient(PlanRoute("multiple_goals")),
            FakePlannerModelClient(_draft()),
            executor,
        )
        result = orchestrator.handle(_request(), trace=trace)

        self.assertEqual(result.status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(result.tool_result["type"], "plan_preview")
        self.assertEqual(len(result.tool_result["steps"]), 2)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(
            [name for name, _ in trace.events if name.startswith(("planning.", "plan."))],
            ["planning.route.selected", "plan.preview.created"],
        )
        planning_payloads = [payload for name, payload in trace.events if name.startswith(("planning.", "plan."))]
        self.assertNotIn("研究并总结", repr(planning_payloads))

    def test_need_user_does_not_create_plan(self) -> None:
        result = self._orchestrator(
            FakePlanningRouteClient(NeedUserRoute("请补充范围。")),
            FakePlannerModelClient(),
            _Executor(),
        ).handle(_request())

        self.assertEqual(result.status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(result.message, "请补充范围。")
        count = self.conn.execute("SELECT COUNT(*) FROM plan_runs").fetchone()[0]
        self.assertEqual(count, 0)

    def test_structured_confirm_executes_current_revision(self) -> None:
        executor = _Executor()
        orchestrator = self._orchestrator(
            FakePlanningRouteClient(PlanRoute("multiple_goals")),
            FakePlannerModelClient(_draft()),
            executor,
        )
        preview_result = orchestrator.handle(_request())
        command = PlanCommand(
            "command_1",
            preview_result.tool_result["plan_id"],
            "session_1",
            preview_result.tool_result["revision"],
            PlanCommandAction.CONFIRM,
        )
        trace = _Trace()
        state = orchestrator.invoke_plan_command(_request(), command, trace=trace)

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(state["result"].message, "finalized")
        self.assertEqual(executor.calls, 2)
        self.assertNotIn("plan_runs", state)
        self.assertNotIn("execution_scope", state)
        names = [name for name, _ in trace.events]
        self.assertEqual(names.count("plan.step.started"), 2)
        self.assertEqual(names.count("plan.step.finished"), 2)
        self.assertIn("plan.finalize.started", names)
        self.assertIn("plan.finalize.completed", names)

    def test_structured_cancel_returns_terminal_result(self) -> None:
        orchestrator = self._orchestrator(
            FakePlanningRouteClient(PlanRoute("multiple_goals")),
            FakePlannerModelClient(_draft()),
            _Executor(),
        )
        preview_result = orchestrator.handle(_request())
        command = PlanCommand(
            "command_cancel",
            preview_result.tool_result["plan_id"],
            "session_1",
            preview_result.tool_result["revision"],
            PlanCommandAction.CANCEL,
        )

        result = orchestrator.invoke_plan_command(_request(), command)["result"]

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertEqual(result.message, "Plan cancelled.")
        self.assertEqual(result.tool_result["type"], "plan_result")
        self.assertEqual(result.tool_result["plan_status"], "cancelled")

    def test_modified_constraint_is_reused_by_automatic_replan(self) -> None:
        planner = FakePlannerModelClient(
            _draft(),
            PlanDraft((PlanStepDraft("modified", 1, "modified", "modified done"),)),
            PlanDraft((PlanStepDraft("retry", 1, "retry", "retry done"),)),
        )
        orchestrator = self._orchestrator(
            FakePlanningRouteClient(PlanRoute("multiple_goals")),
            planner,
            _SequenceExecutor(
                ExecutorResult(
                    "run_1",
                    ExecutorStatus.STOPPED,
                    ExecutorStopReason.GOAL_NOT_ACHIEVED,
                    None,
                    1,
                    error_code="plan_step_goal_not_achieved",
                )
            ),
        )
        initial = orchestrator.handle(_request())
        modified = orchestrator.invoke_plan_command(
            _request(),
            PlanCommand(
                "modify_runtime",
                initial.tool_result["plan_id"],
                "session_1",
                initial.tool_result["revision"],
                PlanCommandAction.MODIFY,
                feedback="保留中文摘要",
            ),
        )["result"]
        replanned = orchestrator.invoke_plan_command(
            _request(),
            PlanCommand(
                "confirm_modified_runtime",
                modified.tool_result["plan_id"],
                "session_1",
                modified.tool_result["revision"],
                PlanCommandAction.CONFIRM,
            ),
        )["result"]

        self.assertEqual(replanned.tool_result["revision"], 3)
        self.assertEqual(
            planner.replan_inputs[0].confirmed_constraints, ("保留中文摘要",)
        )

    def test_cli_translates_only_explicit_plan_command_syntax(self) -> None:
        preview = {"plan_id": "plan_1", "revision": 2, "goal": "研究并总结"}
        command = _parse_plan_command("modify-plan 保留中文摘要", "session_1", preview)

        self.assertEqual(command.action, PlanCommandAction.MODIFY)
        self.assertEqual(command.revision, 2)
        self.assertEqual(command.feedback, "保留中文摘要")
        self.assertIsNone(_parse_plan_command("请确认计划", "session_1", preview))

    def _orchestrator(self, route_client, planner, executor):
        service = PlanningService(planner, self.repo, limits=self.limits)
        controller = PlanController(
            self.repo,
            executor,
            limits=self.limits,
            planner=planner,
            finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("finalized")),
        )
        return RuntimeOrchestrator(
            create_test_skill_service(),
            intent_service=_Intent(),
            policy_service=_Policy(),
            execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
            executor=executor,
            planning_route_client=route_client,
            planning_service=service,
            plan_controller=controller,
            planning_limits=self.limits,
        )


class _Intent:
    def classify(self, request):
        return IntentDecision(IntentType.PLAN_REQUEST, 0.9)


class _Policy:
    def evaluate(self, request, intent):
        return PolicyDecision(PolicyAction.ALLOW, allowed_effects=["read"])


class _Executor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, prompts, tools, scope, trace=None, llm_log=None):
        self.calls += 1
        return ExecutorResult(
            request.run_id,
            ExecutorStatus.COMPLETED,
            ExecutorStopReason.FINAL_ANSWER,
            "direct",
            0,
        )

    def execute_step(self, request, step_input, prompts, tools, scope, trace=None, llm_log=None):
        self.calls += 1
        return ExecutorResult(
            request.run_id,
            ExecutorStatus.COMPLETED,
            ExecutorStopReason.FINAL_ANSWER,
            "step",
            1,
        )


class _SequenceExecutor(_Executor):
    def __init__(self, *results: ExecutorResult) -> None:
        super().__init__()
        self._results = list(results)

    def execute_step(self, request, step_input, prompts, tools, scope, trace=None, llm_log=None):
        self.calls += 1
        return self._results.pop(0)


class _Trace:
    def __init__(self) -> None:
        self.events = []

    def append(self, event_type, payload=None) -> None:
        self.events.append((event_type, payload or {}))


def _draft() -> PlanDraft:
    return PlanDraft(
        (
            PlanStepDraft("one", 1, "first", "first done"),
            PlanStepDraft("two", 2, "second", "second done", ("one",)),
        )
    )


def _request() -> RuntimeRequest:
    return RuntimeRequest("研究并总结", "session_1", run_id="run_1")


if __name__ == "__main__":
    unittest.main()
