from __future__ import annotations

import unittest

from app.planning.errors import PlanContractError, PlanLifecycleError
from app.planning.lifecycle import (
    is_replan_eligible,
    ready_steps,
    record_executor_usage,
    remaining_step_limit,
    transition_plan_run,
    transition_plan_step,
    validate_plan_draft,
)
from app.planning.models import (
    PlanDraft,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepDraft,
    PlanStepStatus,
    PlanningLimits,
)


class PlanningLifecycleTest(unittest.TestCase):
    def test_draft_rejects_cycle_non_contiguous_positions_and_limit(self) -> None:
        cycle = PlanDraft(
            (
                PlanStepDraft("a", 1, "A", "A done", ("b",)),
                PlanStepDraft("b", 2, "B", "B done", ("a",)),
            )
        )
        with self.assertRaises(PlanContractError):
            validate_plan_draft(cycle, PlanningLimits())
        with self.assertRaises(PlanContractError):
            validate_plan_draft(
                PlanDraft((PlanStepDraft("a", 2, "A", "A done"),)), PlanningLimits()
            )
        with self.assertRaises(PlanContractError):
            validate_plan_draft(
                PlanDraft(
                    (
                        PlanStepDraft("a", 1, "A", "A done"),
                        PlanStepDraft("b", 2, "B", "B done"),
                    )
                ),
                PlanningLimits(max_plan_steps=1),
            )

    def test_ready_steps_are_dependency_ready_and_position_ordered(self) -> None:
        steps = (
            _step("third", 3, dependencies=("first",)),
            _step("second", 2),
            _step("first", 1),
        )
        self.assertEqual(tuple(item.step_id for item in ready_steps(steps)), ("first", "second"))
        completed = transition_plan_step(
            steps[2], PlanStepStatus.RUNNING, at="2026-07-14T00:00:00Z"
        )
        completed = transition_plan_step(
            completed,
            PlanStepStatus.COMPLETED,
            at="2026-07-14T00:00:01Z",
            safe_result_summary="first done",
        )
        self.assertEqual(
            tuple(item.step_id for item in ready_steps((steps[0], steps[1], completed))),
            ("second", "third"),
        )

    def test_run_and_step_transitions_reject_illegal_changes(self) -> None:
        run = _run(PlanRunStatus.AWAITING_CONFIRMATION)
        running = transition_plan_run(run, PlanRunStatus.RUNNING, at="2026-07-14T00:00:00Z")
        self.assertEqual(running.status, PlanRunStatus.RUNNING)
        with self.assertRaises(PlanLifecycleError):
            transition_plan_run(run, PlanRunStatus.COMPLETED)
        with self.assertRaises(PlanLifecycleError):
            transition_plan_step(_step("a", 1), PlanStepStatus.COMPLETED)

    def test_budget_accumulates_without_reset_and_bounds_replan(self) -> None:
        limits = PlanningLimits(max_replans=1, max_executor_steps_per_plan_step=3, max_total_executor_steps=4)
        run = _run(PlanRunStatus.RUNNING)
        failed = _step("a", 1, status=PlanStepStatus.GOAL_NOT_ACHIEVED)
        run, failed = record_executor_usage(run, failed, 3, limits)
        self.assertEqual((run.executor_steps_used, failed.executor_steps_used), (3, 3))
        self.assertEqual(remaining_step_limit(run, limits), 1)
        self.assertTrue(is_replan_eligible(run, failed, limits))
        with self.assertRaises(PlanLifecycleError):
            record_executor_usage(run, failed, 2, limits)
        self.assertFalse(is_replan_eligible(run, failed, PlanningLimits(max_replans=0)))


def _run(status: PlanRunStatus) -> PlanRun:
    return PlanRun("plan_1", "session_1", "goal", status)


def _step(
    step_id: str,
    position: int,
    *,
    dependencies: tuple[str, ...] = (),
    status: PlanStepStatus = PlanStepStatus.PENDING,
) -> PlanStep:
    return PlanStep(
        "plan_1", 1, step_id, position, step_id, f"{step_id} done", dependencies, status
    )


if __name__ == "__main__":
    unittest.main()
