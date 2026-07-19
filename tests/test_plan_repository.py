from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.planning.errors import PlanRepositoryError
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
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from tests.helpers import create_test_connection


class PlanRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repo = SqlitePlanRepository(self.conn)
        self.limits = PlanningLimits(max_plan_steps=3, max_replans=1, max_executor_steps_per_plan_step=3, max_total_executor_steps=5)

    def tearDown(self) -> None:
        self.conn.close()

    def test_initial_plan_round_trip_and_confirm_is_idempotent(self) -> None:
        run, steps = self._create()
        command = PlanCommand("command_1", run.plan_id, run.session_id, 1, PlanCommandAction.CONFIRM)
        confirmed, _ = self.repo.apply_command(command)
        duplicate, _ = self.repo.apply_command(command)

        self.assertEqual(confirmed.status, PlanRunStatus.RUNNING)
        self.assertEqual(duplicate, confirmed)
        self.assertEqual(tuple(item.step_id for item in steps), ("read", "write"))

    def test_awaiting_confirmation_is_readable_across_connections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "plans.sqlite3"
            first = connect_sqlite(path)
            migrate(first)
            run, _ = SqlitePlanRepository(first).create_initial_plan(
                session_id="session_1", goal="goal", draft=_draft(), limits=self.limits, plan_id="plan_cross"
            )
            first.close()
            second = connect_sqlite(path)
            try:
                loaded, steps = SqlitePlanRepository(second).get_plan("session_1", run.plan_id)
                self.assertEqual(loaded.status, PlanRunStatus.AWAITING_CONFIRMATION)
                self.assertEqual(len(steps), 2)
            finally:
                second.close()

    def test_stale_revision_cross_session_and_illegal_command_are_rejected(self) -> None:
        run, _ = self._create()
        for command, code in (
            (PlanCommand("a", run.plan_id, "other", 1, PlanCommandAction.CONFIRM), "plan_not_found"),
            (PlanCommand("b", run.plan_id, run.session_id, 2, PlanCommandAction.CONFIRM), "plan_revision_stale"),
        ):
            with self.subTest(code=code), self.assertRaises(PlanRepositoryError) as caught:
                self.repo.apply_command(command)
            self.assertEqual(caught.exception.code, code)
        confirm = PlanCommand("c", run.plan_id, run.session_id, 1, PlanCommandAction.CONFIRM)
        self.repo.apply_command(confirm)
        with self.assertRaises(PlanRepositoryError) as caught:
            self.repo.apply_command(
                PlanCommand("d", run.plan_id, run.session_id, 1, PlanCommandAction.CANCEL)
            )
        self.assertEqual(caught.exception.code, "plan_command_not_allowed")

    def test_modify_creates_revision_and_supersedes_old_pending_steps(self) -> None:
        run, _ = self._create()
        modified, new_steps = self.repo.apply_command(
            PlanCommand("modify_1", run.plan_id, run.session_id, 1, PlanCommandAction.MODIFY, "调整"),
            replacement_draft=PlanDraft((PlanStepDraft("new", 1, "new", "new done"),)),
            limits=self.limits,
        )
        old_steps = self.repo.list_steps(run.plan_id, 1)
        self.assertEqual(modified.current_revision, 2)
        self.assertEqual(new_steps[0].status, PlanStepStatus.PENDING)
        self.assertTrue(all(item.status == PlanStepStatus.SUPERSEDED for item in old_steps))

    def test_claim_and_result_update_step_and_budget_atomically(self) -> None:
        run, _ = self._create()
        self.repo.apply_command(
            PlanCommand("confirm", run.plan_id, run.session_id, 1, PlanCommandAction.CONFIRM)
        )
        claimed = self.repo.claim_ready_step(run.session_id, run.plan_id, 1)
        self.assertEqual(claimed.step_id, "read")
        saved_run, saved_step = self.repo.record_step_result(
            session_id=run.session_id,
            plan_id=run.plan_id,
            revision=1,
            step_id="read",
            status=PlanStepStatus.COMPLETED,
            executor_steps_used=2,
            limits=self.limits,
            safe_result_summary="read done",
            evidence_refs=("evidence:1",),
        )
        self.assertEqual(saved_run.executor_steps_used, 2)
        self.assertEqual(saved_step.executor_steps_used, 2)
        self.assertEqual(saved_step.evidence_refs, ("evidence:1",))
        self.assertEqual(self.repo.claim_ready_step(run.session_id, run.plan_id, 1).step_id, "write")

    def test_failed_atomic_result_does_not_change_step_or_budget(self) -> None:
        run, _ = self._create()
        self.repo.apply_command(
            PlanCommand("confirm", run.plan_id, run.session_id, 1, PlanCommandAction.CONFIRM)
        )
        self.repo.claim_ready_step(run.session_id, run.plan_id, 1)
        with self.assertRaises(PlanRepositoryError):
            self.repo.record_step_result(
                session_id=run.session_id,
                plan_id=run.plan_id,
                revision=1,
                step_id="read",
                status=PlanStepStatus.COMPLETED,
                executor_steps_used=6,
                limits=self.limits,
                safe_result_summary="read done",
            )
        loaded, steps = self.repo.get_plan(run.session_id, run.plan_id)
        self.assertEqual(loaded.executor_steps_used, 0)
        self.assertEqual(steps[0].status, PlanStepStatus.RUNNING)

    def test_replan_preserves_old_completed_result_and_interrupted_run_stops(self) -> None:
        run, _ = self._create()
        self.repo.apply_command(
            PlanCommand("confirm", run.plan_id, run.session_id, 1, PlanCommandAction.CONFIRM)
        )
        self.repo.claim_ready_step(run.session_id, run.plan_id, 1)
        self.repo.record_step_result(
            session_id=run.session_id,
            plan_id=run.plan_id,
            revision=1,
            step_id="read",
            status=PlanStepStatus.COMPLETED,
            executor_steps_used=1,
            limits=self.limits,
            safe_result_summary="safe",
            evidence_refs=("evidence:read",),
        )
        replanned, _ = self.repo.create_replan_revision(
            session_id=run.session_id,
            plan_id=run.plan_id,
            expected_revision=1,
            draft=PlanDraft((PlanStepDraft("retry", 1, "retry", "retry done"),)),
            limits=self.limits,
        )
        old = self.repo.list_steps(run.plan_id, 1)
        self.assertEqual(replanned.status, PlanRunStatus.AWAITING_REPLAN_CONFIRMATION)
        self.assertEqual((old[0].status, old[0].evidence_refs), (PlanStepStatus.COMPLETED, ("evidence:read",)))
        self.assertEqual(
            self.repo.list_completed_steps(run.plan_id, 2)[0].evidence_refs,
            ("evidence:read",),
        )

        self.repo.apply_command(
            PlanCommand("confirm_replan", run.plan_id, run.session_id, 2, PlanCommandAction.CONFIRM)
        )
        self.repo.claim_ready_step(run.session_id, run.plan_id, 2)
        interrupted, steps = self.repo.get_plan(run.session_id, run.plan_id, recover_interrupted=True)
        self.assertEqual(interrupted.last_error_code, "plan_execution_interrupted")
        self.assertEqual((interrupted.status, steps[0].status), (PlanRunStatus.STOPPED, PlanStepStatus.STOPPED))

    def _create(self):
        return self.repo.create_initial_plan(
            session_id="session_1", goal="goal", draft=_draft(), limits=self.limits, plan_id="plan_1"
        )


def _draft() -> PlanDraft:
    return PlanDraft(
        (
            PlanStepDraft("read", 1, "read", "read done"),
            PlanStepDraft("write", 2, "write", "write done", ("read",)),
        )
    )


if __name__ == "__main__":
    unittest.main()
