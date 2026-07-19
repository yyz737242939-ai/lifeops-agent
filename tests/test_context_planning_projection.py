from __future__ import annotations

import unittest

from app.context.models import (
    ContextAssembly,
    ContextContribution,
    ContextContributionKind,
    ContextProvenance,
    ContextQuery,
    ContextQueryOrigin,
    ContextReport,
)
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.planning.models import (
    PlanDraft,
    PlanRoute,
    PlanStepDraft,
    PlannerInput,
    PlanningLimits,
    PlanningRouteInput,
)
from app.planning.planner import FakePlannerModelClient, _planner_payload
from app.planning.repository import SqlitePlanRepository
from app.planning.router import FakePlanningRouteClient, _route_payload
from app.planning.service import PlanningService
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection, create_test_skill_service


class ContextPlanningProjectionTest(unittest.TestCase):
    def test_route_and_planner_inputs_accept_only_bounded_contributions(self) -> None:
        contribution = _contribution()
        limits = PlanningLimits()
        route_input = PlanningRouteInput(
            "goal",
            "plan_request",
            limits=limits,
            context_contributions=(contribution,),
        )
        planner_input = PlannerInput(
            "goal",
            (),
            (),
            limits,
            context_contributions=(contribution,),
        )

        self.assertEqual(route_input.context_contributions, (contribution,))
        self.assertEqual(planner_input.context_contributions, (contribution,))
        self.assertFalse(hasattr(route_input, "context_assembly"))
        self.assertFalse(hasattr(planner_input, "context_report"))
        self.assertEqual(_route_payload(route_input)["context"][0]["content"], "earlier context")
        self.assertEqual(
            _planner_payload("create_plan", planner_input)["context"][0]["kind"],
            "conversation_turn",
        )

    def test_runtime_projects_same_assembly_to_router_and_planner(self) -> None:
        conn = create_test_connection()
        try:
            limits = PlanningLimits(max_plan_steps=2)
            route = FakePlanningRouteClient(PlanRoute("multiple_goals"))
            planner = FakePlannerModelClient(
                PlanDraft((PlanStepDraft("step_1", 1, "读取", "获得结果"),))
            )
            planning_service = PlanningService(
                planner,
                SqlitePlanRepository(conn),
                limits=limits,
            )
            orchestrator = RuntimeOrchestrator(
                create_test_skill_service(),
                intent_service=_Intent(),
                policy_service=_Policy(),
                execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
                planning_route_client=route,
                planning_service=planning_service,
                planning_limits=limits,
            )
            request = RuntimeRequest(
                "完成多步目标",
                "session_1",
                turn_id="turn_1",
                run_id="run_1",
            )
            assembly = _assembly(request)

            orchestrator.invoke(request, context_assembly=assembly)

            self.assertEqual(route.inputs[0].context_contributions, assembly.contributions)
            self.assertEqual(planner.create_inputs[0].context_contributions, assembly.contributions)
            self.assertIs(route.inputs[0].context_contributions, assembly.contributions)
            self.assertIs(planner.create_inputs[0].context_contributions, assembly.contributions)
        finally:
            conn.close()


class _Intent:
    def classify(self, request):
        return IntentDecision(IntentType.PLAN_REQUEST, 1.0)


class _Policy:
    def evaluate(self, request, intent):
        return PolicyDecision(PolicyAction.ALLOW)


def _contribution() -> ContextContribution:
    return ContextContribution(
        ContextContributionKind.CONVERSATION_TURN,
        "conversation.turn",
        "earlier context",
        4,
        ContextProvenance("conversation://session_1/turn_0"),
    )


def _assembly(request: RuntimeRequest) -> ContextAssembly:
    query = ContextQuery(
        request.user_input,
        ContextQueryOrigin.CURRENT_USER_GOAL,
        request.session_id,
        request.run_id,
        request.turn_id,
    )
    report = ContextReport(
        "assembly_1", 1, None, None, False, 0, 0, (), (), (), request.created_at
    )
    return ContextAssembly(
        "assembly_1",
        request.session_id,
        request.run_id,
        request.turn_id,
        query,
        (_contribution(),),
        4,
        report,
    )


if __name__ == "__main__":
    unittest.main()
