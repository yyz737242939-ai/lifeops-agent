from __future__ import annotations

import unittest

from app.executor.models import ExecutorResult, ExecutorStatus, ExecutorStopReason
from app.planning.controller import PlanController
from app.planning.finalizer import FakePlanFinalizerClient
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerOutput,
    PlanRunStatus,
    PlannerInput,
    PlanningLimits,
    PlanStepDraft,
    PlanStepStatus,
)
from app.planning.planner import FakePlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.runtime.models import RuntimeRequest
from app.tools.models import AllowedToolSet
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection


class PlanReplanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repo = SqlitePlanRepository(self.conn)
        self.limits = PlanningLimits(
            max_plan_steps=3,
            max_replans=1,
            max_executor_steps_per_plan_step=3,
            max_total_executor_steps=8,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_goal_not_achieved_creates_preview_and_requires_reconfirmation(self) -> None:
        run = self._create("plan_replan")
        executor = _FakeExecutor(_completed(), _goal_not_achieved(), _completed())
        planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("replacement", 1, "replacement", "replacement done"),))
        )
        controller = PlanController(
            self.repo, executor, limits=self.limits, planner=planner
        )
        trace = _Trace()
        preview = controller.confirm_and_execute(
            _confirm(run.plan_id, 1, "confirm_1"),
            _request(),
            (),
            AllowedToolSet(),
            _runtime(),
            planner_input=_planner_input(self.limits),
            trace=trace,
        )

        self.assertEqual(preview.run.status, PlanRunStatus.AWAITING_REPLAN_CONFIRMATION)
        self.assertEqual(preview.run.current_revision, 2)
        self.assertEqual(len(executor.calls), 2)
        old = self.repo.list_steps(run.plan_id, 1)
        self.assertEqual(old[0].status, PlanStepStatus.COMPLETED)
        self.assertEqual(old[1].status, PlanStepStatus.GOAL_NOT_ACHIEVED)
        self.assertEqual(planner.replan_inputs[0].completed_steps, (old[0],))
        self.assertIn("plan.replan.created", [name for name, _ in trace.events])

        completed = controller.confirm_and_execute(
            _confirm(run.plan_id, 2, "confirm_2"),
            _request(),
            (),
            AllowedToolSet(),
            _runtime(),
            planner_input=_planner_input(self.limits),
        )
        self.assertEqual(completed.run.status, PlanRunStatus.COMPLETED)
        self.assertEqual(len(executor.calls), 3)

    def test_replan_preserves_modified_constraints_and_finalizer_completed_history(self) -> None:
        run = self._create("plan_modified_history")
        modified_draft = PlanDraft(
            (
                PlanStepDraft("first", 1, "first", "first done"),
                PlanStepDraft("failed", 2, "modified", "modified done", ("first",)),
            )
        )
        modified, _ = self.repo.apply_command(
            PlanCommand(
                "modify_1",
                run.plan_id,
                run.session_id,
                1,
                PlanCommandAction.MODIFY,
                feedback="保留中文摘要",
            ),
            replacement_draft=modified_draft,
            limits=self.limits,
        )
        planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("replacement", 1, "replacement", "replacement done"),))
        )
        finalizer = FakePlanFinalizerClient(PlanFinalizerOutput("done"))
        controller = PlanController(
            self.repo,
            _FakeExecutor(_completed(), _goal_not_achieved(), _completed()),
            limits=self.limits,
            planner=planner,
            finalizer=finalizer,
        )
        planner_input = PlannerInput(
            "goal", (), (), self.limits, confirmed_constraints=modified.confirmed_constraints
        )

        preview = controller.confirm_and_execute(
            _confirm(run.plan_id, 2, "confirm_modified"),
            _request(),
            (),
            AllowedToolSet(),
            _runtime(),
            planner_input=planner_input,
        )
        completed = controller.confirm_and_execute(
            _confirm(run.plan_id, preview.run.current_revision, "confirm_replan"),
            _request(),
            (),
            AllowedToolSet(),
            _runtime(),
            planner_input=PlannerInput(
                "goal",
                (),
                (),
                self.limits,
                confirmed_constraints=preview.run.confirmed_constraints,
            ),
        )

        self.assertEqual(
            planner.replan_inputs[0].confirmed_constraints, ("保留中文摘要",)
        )
        self.assertEqual(completed.run.status, PlanRunStatus.COMPLETED)
        self.assertEqual(
            [step.step_id for step in finalizer.inputs[0].step_results],
            ["first", "replacement"],
        )

    def test_second_goal_failure_stops_without_another_replan(self) -> None:
        run = self._create("plan_second_failure", one_step=True)
        planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("replacement", 1, "replacement", "replacement done"),))
        )
        executor = _FakeExecutor(_goal_not_achieved(), _goal_not_achieved())
        controller = PlanController(self.repo, executor, limits=self.limits, planner=planner)
        preview = controller.confirm_and_execute(
            _confirm(run.plan_id, 1, "confirm_1"),
            _request(), (), AllowedToolSet(), _runtime(), planner_input=_planner_input(self.limits)
        )
        stopped = controller.confirm_and_execute(
            _confirm(run.plan_id, 2, "confirm_2"),
            _request(), (), AllowedToolSet(), _runtime(), planner_input=_planner_input(self.limits)
        )
        self.assertEqual(preview.run.status, PlanRunStatus.AWAITING_REPLAN_CONFIRMATION)
        self.assertEqual(stopped.run.status, PlanRunStatus.STOPPED)
        self.assertEqual(stopped.run.last_error_code, "plan_replan_exhausted")
        self.assertEqual(len(planner.replan_inputs), 1)

    def test_single_step_limit_can_replan_but_safety_and_total_budget_cannot(self) -> None:
        run = self._create("plan_limit", one_step=True)
        planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("retry", 1, "retry", "retry done"),))
        )
        limited = _FakeExecutor(_limit_reached(step_count=2))
        preview = PlanController(
            self.repo, limited, limits=self.limits, planner=planner
        ).confirm_and_execute(
            _confirm(run.plan_id, 1, "confirm_limit"),
            _request(), (), AllowedToolSet(), _runtime(), planner_input=_planner_input(self.limits)
        )
        self.assertEqual(preview.run.status, PlanRunStatus.AWAITING_REPLAN_CONFIRMATION)

        safety_run = self._create("plan_safety", one_step=True)
        safety_planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("unused", 1, "unused", "unused done"),))
        )
        safety = PlanController(
            self.repo, _FakeExecutor(_safety_denied()), limits=self.limits, planner=safety_planner
        ).confirm_and_execute(
            _confirm(safety_run.plan_id, 1, "confirm_safety"),
            _request(), (), AllowedToolSet(), _runtime(), planner_input=_planner_input(self.limits)
        )
        self.assertEqual(safety.run.status, PlanRunStatus.STOPPED)
        self.assertEqual(safety_planner.replan_inputs, [])

        tight = PlanningLimits(
            max_plan_steps=1,
            max_replans=1,
            max_executor_steps_per_plan_step=2,
            max_total_executor_steps=2,
        )
        budget_run, _ = self.repo.create_initial_plan(
            session_id="session_1",
            goal="goal",
            draft=PlanDraft((PlanStepDraft("one", 1, "one", "one done"),)),
            limits=tight,
            plan_id="plan_budget_no_replan",
        )
        budget_planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("unused", 1, "unused", "unused done"),))
        )
        budget = PlanController(
            self.repo,
            _FakeExecutor(_limit_reached(step_count=2)),
            limits=tight,
            planner=budget_planner,
        ).confirm_and_execute(
            _confirm(budget_run.plan_id, 1, "confirm_budget"),
            _request(), (), AllowedToolSet(), _runtime(), planner_input=_planner_input(tight)
        )
        self.assertEqual(budget.run.last_error_code, "plan_budget_exhausted")
        self.assertEqual(budget_planner.replan_inputs, [])

    def test_replan_that_recreates_completed_step_stops_without_leaking_exception(self) -> None:
        run = self._create("plan_invalid_replan")
        planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("first", 1, "repeat", "repeat done"),))
        )
        controller = PlanController(
            self.repo,
            _FakeExecutor(_completed(), _limit_reached(step_count=2)),
            limits=self.limits,
            planner=planner,
        )

        result = controller.confirm_and_execute(
            _confirm(run.plan_id, 1, "confirm_invalid_replan"),
            _request(),
            (),
            AllowedToolSet(),
            _runtime(),
            planner_input=_planner_input(self.limits),
        )

        self.assertEqual(result.run.status, PlanRunStatus.STOPPED)
        self.assertEqual(result.run.last_error_code, "plan_contract_invalid")

    def _create(self, plan_id: str, *, one_step: bool = False):
        steps = [PlanStepDraft("first", 1, "first", "first done")]
        if not one_step:
            steps.append(PlanStepDraft("failed", 2, "failed", "failed done", ("first",)))
        return self.repo.create_initial_plan(
            session_id="session_1",
            goal="goal",
            draft=PlanDraft(tuple(steps)),
            limits=self.limits,
            plan_id=plan_id,
        )[0]


class _FakeExecutor:
    def __init__(self, *results: ExecutorResult) -> None:
        self.results = list(results)
        self.calls = []

    def execute_step(self, request, step_input, prompt_contributions, allowed_tools, execution_scope, trace=None, llm_log=None):
        self.calls.append(step_input)
        return self.results.pop(0)


class _Trace:
    def __init__(self) -> None:
        self.events = []

    def append(self, event_type, payload=None) -> None:
        self.events.append((event_type, payload or {}))


def _completed() -> ExecutorResult:
    return ExecutorResult("run_1", ExecutorStatus.COMPLETED, ExecutorStopReason.FINAL_ANSWER, "done", 1)


def _goal_not_achieved() -> ExecutorResult:
    return ExecutorResult(
        "run_1", ExecutorStatus.STOPPED, ExecutorStopReason.GOAL_NOT_ACHIEVED, None, 1,
        error_code="plan_step_goal_not_achieved",
    )


def _limit_reached(*, step_count: int) -> ExecutorResult:
    return ExecutorResult("run_1", ExecutorStatus.STOPPED, ExecutorStopReason.LIMIT_REACHED, None, step_count)


def _safety_denied() -> ExecutorResult:
    return ExecutorResult(
        "run_1", ExecutorStatus.STOPPED, ExecutorStopReason.SAFETY_DENIED, None, 1,
        error_code="tool_not_allowed",
    )


def _confirm(plan_id: str, revision: int, command_id: str) -> PlanCommand:
    return PlanCommand(command_id, plan_id, "session_1", revision, PlanCommandAction.CONFIRM)


def _planner_input(limits: PlanningLimits) -> PlannerInput:
    return PlannerInput("goal", (), (), limits)


def _request() -> RuntimeRequest:
    return RuntimeRequest("goal", "session_1", run_id="run_1")


def _runtime() -> ToolRuntime:
    return ToolRuntime.from_registry(ToolRegistry())


if __name__ == "__main__":
    unittest.main()
