from __future__ import annotations

import unittest
from dataclasses import fields

from app.planning.errors import PlanContractError, PlanningError
from app.planning.models import (
    DirectRoute,
    NeedUserRoute,
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanRoute,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepDraft,
    PlanStepStatus,
    PlanningLimits,
)


class PlanningModelsTest(unittest.TestCase):
    def test_limits_defaults_and_invalid_values(self) -> None:
        self.assertEqual(PlanningLimits(), PlanningLimits(6, 1, 6, 24))
        for kwargs in (
            {"max_plan_steps": 0},
            {"max_replans": -1},
            {"max_executor_steps_per_plan_step": 0},
            {"max_total_executor_steps": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PlanningLimits(**kwargs)

    def test_route_decisions_are_mutually_typed(self) -> None:
        self.assertEqual(DirectRoute("single_goal").reason_code, "single_goal")
        self.assertEqual(PlanRoute("explicit_dependencies").reason_code, "explicit_dependencies")
        self.assertEqual(NeedUserRoute("请补充日期。").question, "请补充日期。")

    def test_plan_draft_rejects_duplicate_unknown_and_self_dependencies(self) -> None:
        first = PlanStepDraft("step_1", 1, "读取", "获得数据")
        with self.assertRaises(ValueError):
            PlanDraft((first, PlanStepDraft("step_1", 2, "整理", "完成")))
        with self.assertRaises(ValueError):
            PlanDraft((first, PlanStepDraft("step_2", 2, "整理", "完成", ("missing",))))
        with self.assertRaises(ValueError):
            PlanStepDraft("step_1", 1, "读取", "获得数据", ("step_1",))

    def test_plan_run_step_and_command_validate_identity_and_revision(self) -> None:
        run = PlanRun("plan_1", "session_1", "完成研究", PlanRunStatus.AWAITING_CONFIRMATION)
        step = PlanStep(
            "plan_1", 1, "step_1", 1, "读取", "获得数据", (), PlanStepStatus.PENDING
        )
        command = PlanCommand(
            "command_1", "plan_1", "session_1", 1, PlanCommandAction.CONFIRM
        )
        self.assertEqual((run.current_revision, step.revision, command.revision), (1, 1, 1))
        with self.assertRaises(ValueError):
            PlanStep(
                "plan_1", 1, "done", 1, "读取", "获得数据", (), PlanStepStatus.COMPLETED
            )
        with self.assertRaises(ValueError):
            PlanCommand("command_2", "plan_1", "session_1", 1, PlanCommandAction.MODIFY)

    def test_public_fields_and_error_hierarchy_are_explicit(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(PlanStepDraft)),
            ("step_id", "position", "objective", "expected_outcome", "dependency_step_ids"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(PlanRun)),
            (
                "plan_id",
                "session_id",
                "goal",
                "status",
                "current_revision",
                "replan_count",
                "executor_steps_used",
                "created_at",
                "updated_at",
                "confirmed_at",
                "completed_at",
                "last_error_code",
                "confirmed_constraints",
            ),
        )
        self.assertTrue(issubclass(PlanContractError, PlanningError))


if __name__ == "__main__":
    unittest.main()
