import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.agent import Agent
from app.planning.plan_types import PlanRun, PlanStep
from app.planning.planner_agent import PlannerResult


class FakePlannerAgent:
    def __init__(self) -> None:
        self.goals: list[str] = []

    def plan(self, *, goal: str, **_kwargs) -> PlannerResult:
        self.goals.append(goal)
        return PlannerResult(
            output_type="plan",
            message="请确认计划。",
            plan=PlanRun(
                goal=goal,
                source_user_input_summary=goal,
                steps=[
                    PlanStep(title="Read scope", intent="Inspect the requested scope."),
                    PlanStep(title="Make change", intent="Apply the smallest patch."),
                ],
            ),
        )


class WriteLookingPlannerAgent:
    def plan(self, *, goal: str, **_kwargs) -> PlannerResult:
        return PlannerResult(
            output_type="plan",
            message="请确认计划。",
            plan=PlanRun(
                goal=goal,
                source_user_input_summary=goal,
                steps=[
                    PlanStep(
                        title="Create a task",
                        intent="Create a task named unsafe planner write.",
                        expected_tool_domain="tasks",
                    ),
                ],
            ),
        )


def _tool_names(call) -> set[str]:
    return {schema["name"] for schema in call.kwargs["tools"]}


class AgentPlanningOrchestratorTests(unittest.TestCase):
    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_simple_request_still_direct_executes_without_plan(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="done")
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)

        answer = agent.chat("现在几点？")

        self.assertEqual(answer, "done")
        self.assertIsNone(agent.planning_state.pending_plan)
        self.assertIsNone(agent.planning_state.active_plan)
        self.assertEqual(planner.goals, [])
        self.assertEqual(create_response.call_count, 1)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_direct_todo_write_with_plan_word_does_not_preview_plan(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(
            output=[],
            output_text="我还没有保存这个待办。",
        )
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)

        answer = agent.chat("帮我添加一个待办：写 Plan and Execute 手动测试记录")

        self.assertEqual(answer, "我还没有保存这个待办。")
        self.assertIsNone(agent.planning_state.pending_plan)
        self.assertEqual(planner.goals, [])
        self.assertEqual(create_response.call_count, 1)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_complex_request_previews_plan_without_agent_llm_or_tools(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)

        answer = agent.chat("帮我分步骤完成 Plan and Execute v0。")

        self.assertIn("等待确认", answer)
        self.assertIsNotNone(agent.planning_state.pending_plan)
        self.assertIsNone(agent.planning_state.active_plan)
        self.assertEqual(planner.goals, ["帮我分步骤完成 Plan and Execute v0。"])
        create_response.assert_not_called()

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_pending_plan_confirm_executes_first_step_once(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="first step done")
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")

        answer = agent.chat("确认")

        self.assertIn("first step done", answer)
        self.assertIn("下一步是", answer)
        self.assertIsNone(agent.planning_state.pending_plan)
        self.assertIsNotNone(agent.planning_state.active_plan)
        assert agent.planning_state.active_plan is not None
        self.assertEqual(agent.planning_state.active_plan.status, "active")
        self.assertEqual(agent.planning_state.active_plan.steps[0].status, "done")
        self.assertEqual(agent.planning_state.active_plan.current_step_id, agent.planning_state.active_plan.steps[1].step_id)
        self.assertEqual(create_response.call_count, 1)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_active_plan_continue_executes_only_next_step(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="step done")
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")
        agent.chat("确认")

        answer = agent.chat("继续")

        self.assertIn("step done", answer)
        assert agent.planning_state.active_plan is not None
        self.assertEqual(agent.planning_state.active_plan.status, "completed")
        self.assertEqual(create_response.call_count, 2)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_active_plan_confirm_executes_next_step(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="step done")
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")
        agent.chat("确认")

        answer = agent.chat("确认")

        self.assertIn("step done", answer)
        assert agent.planning_state.active_plan is not None
        self.assertEqual(agent.planning_state.active_plan.status, "completed")
        self.assertEqual(create_response.call_count, 2)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_step_failure_marks_current_step_failed(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.side_effect = RuntimeError("planner step failed")
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")

        answer = agent.chat("确认")

        self.assertIn("模型请求失败", answer)
        assert agent.planning_state.active_plan is not None
        self.assertEqual(agent.planning_state.active_plan.steps[0].status, "failed")
        self.assertEqual(agent.planning_state.active_plan.steps[1].status, "pending")
        self.assertIsNotNone(agent.planning_state.pending_plan)
        self.assertIn("修订计划等待确认", answer)
        self.assertIn("等待确认", answer)
        self.assertEqual(len(planner.goals), 2)
        self.assertIn("Replan after a failed", planner.goals[-1])

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_failed_step_replan_waits_for_user_confirmation(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.side_effect = [
            RuntimeError("planner step failed"),
            SimpleNamespace(output=[], output_text="replanned step done"),
        ]
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")
        agent.chat("确认")
        pending_replan = agent.planning_state.pending_plan
        assert pending_replan is not None

        answer = agent.chat("确认")

        self.assertIn("replanned step done", answer)
        self.assertIsNone(agent.planning_state.pending_plan)
        assert agent.planning_state.active_plan is not None
        self.assertEqual(agent.planning_state.active_plan.plan_id, pending_replan.plan_id)
        self.assertEqual(create_response.call_count, 2)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_step_run_state_and_recovery_record_include_plan_ids(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="first step done")
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")
        pending_plan = agent.planning_state.pending_plan
        assert pending_plan is not None
        first_step = pending_plan.steps[0]

        agent.chat("确认")

        state = agent.last_run_state
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.plan_id, pending_plan.plan_id)
        self.assertEqual(state.plan_step_id, first_step.step_id)
        run_record = agent.recovery_store.list_recent_runs(limit=1)[0]
        self.assertEqual(run_record.plan_id, pending_plan.plan_id)
        self.assertEqual(run_record.plan_step_id, first_step.step_id)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_executor_step_does_not_authorize_write_from_planner_text(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="read-only")
        agent = Agent(planner_agent=WriteLookingPlannerAgent())
        agent.chat("帮我分步骤完成任务创建。")

        agent.chat("确认")

        tools = _tool_names(create_response.call_args)
        self.assertNotIn("create_task", tools)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_pending_plan_cancel_finishes_without_execution(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")

        answer = agent.chat("取消")

        self.assertIn("已取消计划", answer)
        self.assertIsNone(agent.planning_state.pending_plan)
        self.assertIsNone(agent.planning_state.active_plan)
        create_response.assert_not_called()

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_active_plan_cancel_prevents_later_step_execution(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        create_response.return_value = SimpleNamespace(output=[], output_text="step done")
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")
        agent.chat("确认")

        answer = agent.chat("取消")

        self.assertIn("已取消 active 计划", answer)
        self.assertIsNone(agent.planning_state.active_plan)
        self.assertEqual(create_response.call_count, 1)

        agent.chat("继续")

        self.assertEqual(create_response.call_count, 2)
        self.assertIsNone(agent.planning_state.active_plan)

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_pending_plan_modify_supersedes_old_plan(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)
        agent.chat("帮我分步骤完成 Plan and Execute v0。")
        old_plan = agent.planning_state.pending_plan

        answer = agent.chat("修改：先写测试。")

        self.assertIn("等待确认", answer)
        self.assertIsNotNone(agent.planning_state.pending_plan)
        assert old_plan is not None
        self.assertEqual(old_plan.status, "superseded")
        self.assertEqual(planner.goals[-1], "修改：先写测试。")
        create_response.assert_not_called()

    @patch("app.agents.agent.llm_io")
    @patch("app.agents.agent.events")
    @patch("app.agents.agent.client.responses.create")
    def test_risky_request_still_uses_interaction_safety(
        self,
        create_response,
        _events,
        _llm_io,
    ) -> None:
        planner = FakePlannerAgent()
        agent = Agent(planner_agent=planner)

        answer = agent.chat("删除所有已完成待办。")

        self.assertIn("高风险操作", answer)
        self.assertIsNone(agent.planning_state.pending_plan)
        self.assertEqual(planner.goals, [])
        create_response.assert_not_called()


if __name__ == "__main__":
    unittest.main()
