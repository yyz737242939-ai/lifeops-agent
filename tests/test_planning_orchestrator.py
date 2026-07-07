import unittest

from app.planning.orchestrator import PlanningOrchestrator, PlanningRoute
from app.planning.plan_types import PlanRun, PlanStep
from app.planning.planner_agent import PlannerResult
from app.planning.planning_state import PlanningState


class FakePlannerAgent:
    def __init__(self) -> None:
        self.goals: list[str] = []

    def plan(self, *, goal: str, **_kwargs) -> PlannerResult:
        self.goals.append(goal)
        return PlannerResult(
            output_type="plan",
            message="请先确认这个计划。",
            plan=PlanRun(
                goal=goal,
                source_user_input_summary=goal,
                steps=[
                    PlanStep(title="Inspect scope", intent="Read the relevant plan."),
                    PlanStep(title="Implement safely", intent="Make the smallest change."),
                ],
            ),
        )


class NeedUserPlannerAgent:
    def __init__(self) -> None:
        self.goals: list[str] = []

    def plan(self, *, goal: str, **_kwargs) -> PlannerResult:
        self.goals.append(goal)
        return PlannerResult(
            output_type="need_user",
            message="请补充范围。",
        )


class PlanningOrchestratorTests(unittest.TestCase):
    def test_simple_request_routes_to_direct_execute_without_plan(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )

        result = orchestrator.route("现在几点？")

        self.assertEqual(result.route, PlanningRoute.DIRECT_EXECUTE)
        self.assertFalse(result.handled)
        self.assertIsNone(state.pending_plan)
        self.assertEqual(planner.goals, [])

    def test_complex_request_previews_plan_without_execution(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )

        result = orchestrator.route("帮我分步骤完成 Plan and Execute v0。")

        self.assertEqual(result.route, PlanningRoute.PLAN_PREVIEW)
        self.assertTrue(result.handled)
        self.assertIsNotNone(state.pending_plan)
        self.assertIsNone(state.active_plan)
        self.assertIn("等待确认", result.answer or "")
        self.assertEqual(planner.goals, ["帮我分步骤完成 Plan and Execute v0。"])

    def test_pending_plan_confirm_requests_current_step_execution(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )
        orchestrator.route("帮我分步骤完成 Plan and Execute v0。")

        result = orchestrator.route("确认")

        self.assertEqual(result.route, PlanningRoute.CONFIRM_PLAN)
        self.assertFalse(result.handled)
        self.assertTrue(result.execute_current_step)
        self.assertIsNone(state.pending_plan)
        self.assertIsNotNone(state.active_plan)
        assert state.active_plan is not None
        self.assertEqual(state.active_plan.status, "active")

    def test_active_plan_continue_requests_current_step_execution(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )
        orchestrator.route("帮我分步骤完成 Plan and Execute v0。")
        orchestrator.route("确认")

        result = orchestrator.route("继续")

        self.assertEqual(result.route, PlanningRoute.EXECUTE_STEP)
        self.assertFalse(result.handled)
        self.assertTrue(result.execute_current_step)

    def test_cancel_pending_plan_does_not_execute(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )
        orchestrator.route("帮我分步骤完成 Plan and Execute v0。")
        old_plan = state.pending_plan

        result = orchestrator.route("取消")

        self.assertEqual(result.route, PlanningRoute.CANCEL_PLAN)
        self.assertTrue(result.handled)
        self.assertIsNone(state.pending_plan)
        self.assertIsNone(state.active_plan)
        assert old_plan is not None
        self.assertEqual(old_plan.status, "cancelled")

    def test_modify_pending_plan_supersedes_old_plan(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )
        orchestrator.route("帮我分步骤完成 Plan and Execute v0。")
        old_plan = state.pending_plan

        result = orchestrator.route("修改：先写测试。")

        self.assertEqual(result.route, PlanningRoute.MODIFY_PLAN)
        self.assertTrue(result.handled)
        self.assertIsNotNone(state.pending_plan)
        assert old_plan is not None
        self.assertEqual(old_plan.status, "superseded")
        self.assertEqual(planner.goals[-1], "修改：先写测试。")

    def test_ambiguous_request_asks_for_clarification(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )

        result = orchestrator.route("帮我处理一下")

        self.assertEqual(result.route, PlanningRoute.CLARIFY)
        self.assertTrue(result.handled)
        self.assertIn("不够明确", result.answer or "")
        self.assertEqual(planner.goals, [])

    def test_risky_request_routes_to_safety_pending(self) -> None:
        state = PlanningState()
        planner = FakePlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )

        result = orchestrator.route("删除所有已完成待办。")

        self.assertEqual(result.route, PlanningRoute.SAFETY_PENDING)
        self.assertFalse(result.handled)
        self.assertIsNone(state.pending_plan)

    def test_planner_need_user_does_not_create_pending_plan(self) -> None:
        state = PlanningState()
        planner = NeedUserPlannerAgent()
        orchestrator = PlanningOrchestrator(
            planning_state=state,
            planner_agent=planner,
        )

        result = orchestrator.route("帮我分步骤完成这个。")

        self.assertEqual(result.route, PlanningRoute.CLARIFY)
        self.assertTrue(result.handled)
        self.assertFalse(result.execute_current_step)
        self.assertIn("补充范围", result.answer or "")
        self.assertIsNone(state.pending_plan)
        self.assertIsNone(state.active_plan)


if __name__ == "__main__":
    unittest.main()
