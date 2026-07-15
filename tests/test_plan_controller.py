from __future__ import annotations

import unittest

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    ToolObservation,
)
from app.planning.controller import PlanController
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanRunStatus,
    PlanStepDraft,
    PlanStepStatus,
    PlanningLimits,
)
from app.planning.repository import SqlitePlanRepository
from app.runtime.models import RuntimeRequest
from app.tools.models import AllowedToolSet, ToolCallStatus
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection


class PlanControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repo = SqlitePlanRepository(self.conn)
        self.limits = PlanningLimits(
            max_plan_steps=4,
            max_executor_steps_per_plan_step=3,
            max_total_executor_steps=6,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_serial_order_shared_scope_and_declared_dependency_handoff(self) -> None:
        run, _ = self.repo.create_initial_plan(
            session_id="session_1",
            goal="goal",
            draft=PlanDraft(
                (
                    PlanStepDraft("first", 1, "first", "first done"),
                    PlanStepDraft("second", 2, "second", "second done"),
                    PlanStepDraft("third", 3, "third", "third done", ("first",)),
                )
            ),
            limits=self.limits,
            plan_id="plan_1",
        )
        executor = _FakeStepExecutor(
            _completed("run_1", "first", output={"document_id": "doc_1"}),
            _completed("run_1", "second", output={"other_id": "other_1"}),
            _completed("run_1", "third"),
        )
        runtime = ToolRuntime.from_registry(ToolRegistry())
        result = PlanController(self.repo, executor, limits=self.limits).confirm_and_execute(
            _confirm(run.plan_id), _request(), (), AllowedToolSet(), runtime
        )

        self.assertEqual(result.run.status, PlanRunStatus.COMPLETED)
        self.assertEqual([item.step_input.step_id for item in executor.calls], ["first", "second", "third"])
        self.assertTrue(all(item.execution_scope is runtime for item in executor.calls))
        third_dependencies = executor.calls[2].step_input.dependency_results
        self.assertEqual(tuple(item.step_id for item in third_dependencies), ("first",))
        self.assertEqual(third_dependencies[0].observations[0].output["document_id"], "doc_1")
        self.assertTrue(all(item.status == PlanStepStatus.COMPLETED for item in result.steps))

    def test_budget_stops_before_claiming_another_step(self) -> None:
        limits = PlanningLimits(
            max_plan_steps=3,
            max_executor_steps_per_plan_step=2,
            max_total_executor_steps=3,
        )
        run, _ = self.repo.create_initial_plan(
            session_id="session_1",
            goal="goal",
            draft=PlanDraft(
                tuple(PlanStepDraft(f"s{i}", i, f"s{i}", f"s{i} done") for i in range(1, 4))
            ),
            limits=limits,
            plan_id="plan_budget",
        )
        executor = _FakeStepExecutor(
            _completed("run_1", "s1", step_count=2),
            _completed("run_1", "s2", step_count=1),
        )
        result = PlanController(self.repo, executor, limits=limits).confirm_and_execute(
            _confirm(run.plan_id), _request(), (), AllowedToolSet(), ToolRuntime.from_registry(ToolRegistry())
        )
        self.assertEqual(result.run.status, PlanRunStatus.STOPPED)
        self.assertEqual(result.run.last_error_code, "plan_budget_exhausted")
        self.assertEqual([item.step_input.max_steps for item in executor.calls], [2, 1])
        self.assertEqual(result.steps[2].status, PlanStepStatus.PENDING)

    def test_structured_stop_does_not_execute_later_steps(self) -> None:
        run, _ = self.repo.create_initial_plan(
            session_id="session_1",
            goal="goal",
            draft=PlanDraft(
                (
                    PlanStepDraft("one", 1, "one", "one done"),
                    PlanStepDraft("two", 2, "two", "two done", ("one",)),
                )
            ),
            limits=self.limits,
            plan_id="plan_stop",
        )
        executor = _FakeStepExecutor(
            ExecutorResult(
                "run_1",
                ExecutorStatus.STOPPED,
                ExecutorStopReason.SAFETY_DENIED,
                None,
                1,
                error_code="tool_not_allowed",
            )
        )
        result = PlanController(self.repo, executor, limits=self.limits).confirm_and_execute(
            _confirm(run.plan_id), _request(), (), AllowedToolSet(), ToolRuntime.from_registry(ToolRegistry())
        )
        self.assertEqual(result.run.status, PlanRunStatus.STOPPED)
        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(result.steps[0].status, PlanStepStatus.STOPPED)
        self.assertEqual(result.steps[1].status, PlanStepStatus.PENDING)

    def test_duplicate_confirm_does_not_start_second_controller(self) -> None:
        run, _ = self.repo.create_initial_plan(
            session_id="session_1",
            goal="goal",
            draft=PlanDraft((PlanStepDraft("one", 1, "one", "one done"),)),
            limits=self.limits,
            plan_id="plan_duplicate",
        )
        executor = _FakeStepExecutor(_completed("run_1", "one"))
        controller = PlanController(self.repo, executor, limits=self.limits)
        command = _confirm(run.plan_id)
        first = controller.confirm_and_execute(
            command, _request(), (), AllowedToolSet(), ToolRuntime.from_registry(ToolRegistry())
        )
        second = controller.confirm_and_execute(
            command, _request(), (), AllowedToolSet(), ToolRuntime.from_registry(ToolRegistry())
        )
        self.assertEqual((first.run.status, second.run.status), (PlanRunStatus.COMPLETED, PlanRunStatus.COMPLETED))
        self.assertEqual(len(executor.calls), 1)


class _Call:
    def __init__(self, step_input, execution_scope) -> None:
        self.step_input = step_input
        self.execution_scope = execution_scope


class _FakeStepExecutor:
    def __init__(self, *results: ExecutorResult) -> None:
        self.results = list(results)
        self.calls = []

    def execute_step(
        self,
        request,
        step_input,
        prompt_contributions,
        allowed_tools,
        execution_scope,
        trace=None,
        llm_log=None,
    ) -> ExecutorResult:
        self.calls.append(_Call(step_input, execution_scope))
        return self.results.pop(0)


def _completed(
    run_id: str,
    step_id: str,
    *,
    output: dict | None = None,
    step_count: int = 1,
) -> ExecutorResult:
    observations = (
        ToolObservation(
            1,
            f"call_{step_id}",
            "test.read",
            ToolCallStatus.SUCCEEDED,
            output or {},
        ),
    )
    return ExecutorResult(
        run_id,
        ExecutorStatus.COMPLETED,
        ExecutorStopReason.FINAL_ANSWER,
        "done",
        step_count,
        observations,
    )


def _confirm(plan_id: str) -> PlanCommand:
    return PlanCommand("confirm_1", plan_id, "session_1", 1, PlanCommandAction.CONFIRM)


def _request() -> RuntimeRequest:
    return RuntimeRequest("goal", "session_1", run_id="run_1")


if __name__ == "__main__":
    unittest.main()
