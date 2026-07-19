from __future__ import annotations

import inspect
import unittest

from app.planning.errors import PlanContractError, PlanRepositoryError
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanPreview,
    PlanRunStatus,
    PlannerInput,
    PlannerNeedUser,
    PlanningLimits,
    PlanningScopeRef,
    PlanningSnapshotEnvelope,
    PlanStepDraft,
    PlanStepStatus,
)
from app.planning.planner import FakePlannerModelClient, FakePlanningSnapshotProvider
from app.planning.repository import SqlitePlanRepository
from app.planning.service import PlanningService
from tests.helpers import create_test_connection


class PlanningServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repo = SqlitePlanRepository(self.conn)
        self.limits = PlanningLimits(max_plan_steps=3)

    def tearDown(self) -> None:
        self.conn.close()

    def test_create_and_read_preview_is_awaiting_confirmation(self) -> None:
        planner = FakePlannerModelClient(_draft())
        service = PlanningService(planner, self.repo, limits=self.limits)
        preview = service.create_preview("session_1", _input(self.limits))

        self.assertIsInstance(preview, PlanPreview)
        self.assertEqual(preview.run.status, PlanRunStatus.AWAITING_CONFIRMATION)
        self.assertEqual(service.get_preview("session_1", preview.run.plan_id), preview)
        self.assertEqual(planner.create_inputs, [_input(self.limits)])

    def test_trusted_scope_refs_are_loaded_through_snapshot_provider(self) -> None:
        envelope = PlanningSnapshotEnvelope(
            "research", "topic_1", {"source_count": 2}
        )
        planner = FakePlannerModelClient(_draft())
        snapshots = FakePlanningSnapshotProvider(envelope)
        service = PlanningService(
            planner,
            self.repo,
            limits=self.limits,
            snapshot_provider=snapshots,
        )
        refs = (PlanningScopeRef("research", "topic_1"),)

        service.create_preview(
            "session_1", _input(self.limits), scope_refs=refs
        )

        self.assertEqual(snapshots.requests, [refs])
        self.assertEqual(planner.create_inputs[0].snapshots, (envelope,))

    def test_clarification_does_not_create_durable_plan(self) -> None:
        service = PlanningService(
            FakePlannerModelClient(PlannerNeedUser("请补充主题。")), self.repo, limits=self.limits
        )
        result = service.create_preview("session_1", _input(self.limits))
        count = self.conn.execute("SELECT COUNT(*) AS count FROM plan_runs").fetchone()["count"]
        self.assertEqual(result, PlannerNeedUser("请补充主题。"))
        self.assertEqual(count, 0)

    def test_confirm_is_idempotent_and_does_not_have_executor_dependency(self) -> None:
        service = PlanningService(FakePlannerModelClient(_draft()), self.repo, limits=self.limits)
        preview = service.create_preview("session_1", _input(self.limits))
        command = PlanCommand(
            "confirm_1", preview.run.plan_id, "session_1", 1, PlanCommandAction.CONFIRM
        )
        first = service.confirm(command)
        duplicate = service.confirm(command)

        self.assertEqual(first.run.status, PlanRunStatus.RUNNING)
        self.assertEqual(duplicate, first)
        self.assertNotIn("executor", inspect.signature(PlanningService).parameters)
        self.assertTrue(all(item.status == PlanStepStatus.PENDING for item in first.steps))

    def test_cancel_and_modify_are_revision_bound(self) -> None:
        planner = FakePlannerModelClient(_draft(), _modified_draft(), _draft())
        service = PlanningService(planner, self.repo, limits=self.limits)
        first = service.create_preview("session_1", _input(self.limits))
        modified = service.modify_preview(
            PlanCommand(
                "modify_1",
                first.run.plan_id,
                "session_1",
                1,
                PlanCommandAction.MODIFY,
                "先保留已有资料",
            ),
            _input(self.limits),
        )
        self.assertEqual(modified.run.current_revision, 2)
        self.assertEqual(planner.create_inputs[-1].confirmed_constraints, ("先保留已有资料",))

        with self.assertRaises(PlanRepositoryError) as stale:
            service.cancel(
                PlanCommand(
                    "cancel_stale",
                    first.run.plan_id,
                    "session_1",
                    1,
                    PlanCommandAction.CANCEL,
                )
            )
        self.assertEqual(stale.exception.code, "plan_revision_stale")
        cancelled = service.cancel(
            PlanCommand(
                "cancel_2",
                first.run.plan_id,
                "session_1",
                2,
                PlanCommandAction.CANCEL,
            )
        )
        self.assertEqual(cancelled.run.status, PlanRunStatus.CANCELLED)
        self.assertTrue(
            all(step.status == PlanStepStatus.CANCELLED for step in cancelled.steps)
        )

    def test_cross_session_wrong_action_and_limit_override_fail_closed(self) -> None:
        service = PlanningService(FakePlannerModelClient(_draft()), self.repo, limits=self.limits)
        preview = service.create_preview("session_1", _input(self.limits))
        with self.assertRaises(PlanRepositoryError) as cross_session:
            service.confirm(
                PlanCommand(
                    "confirm_other",
                    preview.run.plan_id,
                    "session_2",
                    1,
                    PlanCommandAction.CONFIRM,
                )
            )
        self.assertEqual(cross_session.exception.code, "plan_not_found")
        with self.assertRaises(PlanContractError):
            service.confirm(
                PlanCommand(
                    "wrong_action",
                    preview.run.plan_id,
                    "session_1",
                    1,
                    PlanCommandAction.CANCEL,
                )
            )
        with self.assertRaises(PlanContractError):
            service.create_preview("session_1", _input(PlanningLimits(max_plan_steps=6)))


def _input(limits: PlanningLimits) -> PlannerInput:
    return PlannerInput("goal", (), (), limits)


def _draft() -> PlanDraft:
    return PlanDraft((PlanStepDraft("one", 1, "one", "one done"),))


def _modified_draft() -> PlanDraft:
    return PlanDraft((PlanStepDraft("new", 1, "new", "new done"),))


if __name__ == "__main__":
    unittest.main()
