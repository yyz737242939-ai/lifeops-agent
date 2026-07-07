import unittest

from pydantic import ValidationError

from app.planning.plan_types import PlanRun, PlanStep
from app.planning.planning_state import PlanningState


def make_step(title: str = "Inspect current state") -> PlanStep:
    return PlanStep(title=title, intent=f"{title}.")


class PlanRunTests(unittest.TestCase):
    def test_pending_plan_confirm_becomes_active_with_current_step(self) -> None:
        first = make_step("Read plan")
        plan = PlanRun(
            goal="Implement Plan and Execute Step 1",
            steps=[first, make_step("Add tests")],
            source_user_input_summary="Start first step.",
        )

        current = plan.confirm()

        self.assertIs(current, first)
        self.assertEqual(plan.status, "active")
        self.assertEqual(plan.current_step_id, first.step_id)

    def test_current_step_id_must_reference_existing_step(self) -> None:
        with self.assertRaises(ValueError):
            PlanRun(
                goal="Invalid plan",
                steps=[make_step()],
                current_step_id="plan_step_missing",
                source_user_input_summary="Invalid input.",
            )

    def test_plan_requires_at_least_one_step(self) -> None:
        with self.assertRaises(ValidationError):
            PlanRun(
                goal="Invalid plan",
                steps=[],
                source_user_input_summary="Invalid input.",
            )

    def test_terminal_plan_cannot_continue_changing(self) -> None:
        plan = PlanRun(
            goal="Cancel obsolete plan",
            steps=[make_step()],
            source_user_input_summary="Cancel it.",
        )

        plan.cancel()

        self.assertEqual(plan.status, "cancelled")
        with self.assertRaises(RuntimeError):
            plan.supersede()

    def test_step_status_update_advances_and_completes_plan(self) -> None:
        first = make_step("First")
        second = make_step("Second")
        plan = PlanRun(
            goal="Run two steps",
            steps=[first, second],
            source_user_input_summary="Do two things.",
        )
        plan.confirm()

        done_first = plan.mark_current_step_done(
            last_run_id="run-1",
            result_summary="First done.",
        )

        self.assertIs(done_first, first)
        self.assertEqual(first.status, "done")
        self.assertEqual(first.last_run_id, "run-1")
        self.assertEqual(plan.current_step_id, second.step_id)

        plan.mark_current_step_done(result_summary="Second done.")

        self.assertEqual(plan.status, "completed")
        self.assertIsNone(plan.current_step_id)


class PlanningStateTests(unittest.TestCase):
    def test_creates_pending_plan(self) -> None:
        state = PlanningState()

        plan = state.create_pending_plan(
            goal="Prepare a complex workflow",
            steps=[make_step()],
            source_user_input_summary="Prepare workflow.",
        )

        self.assertIs(state.pending_plan, plan)
        self.assertEqual(plan.status, "pending_confirmation")
        self.assertIsNone(state.active_plan)

    def test_confirm_pending_plan_moves_it_to_active(self) -> None:
        state = PlanningState()
        plan = state.create_pending_plan(
            goal="Prepare a complex workflow",
            steps=[make_step()],
            source_user_input_summary="Prepare workflow.",
        )

        confirmed = state.confirm_pending_plan()

        self.assertIs(confirmed, plan)
        self.assertIsNone(state.pending_plan)
        self.assertIs(state.active_plan, plan)
        self.assertEqual(plan.status, "active")
        self.assertIsNotNone(state.current_step)

    def test_cancel_after_pending_plan_prevents_execution(self) -> None:
        state = PlanningState()
        state.create_pending_plan(
            goal="Prepare a complex workflow",
            steps=[make_step()],
            source_user_input_summary="Prepare workflow.",
        )

        cancelled = state.cancel_pending_plan()

        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNone(state.pending_plan)
        self.assertIsNone(state.active_plan)
        with self.assertRaises(RuntimeError):
            state.start_current_step()

    def test_supersede_replaces_active_plan_with_new_pending_plan(self) -> None:
        state = PlanningState()
        old_plan = state.create_pending_plan(
            goal="Old workflow",
            steps=[make_step("Old step")],
            source_user_input_summary="Old.",
        )
        state.confirm_pending_plan()

        new_plan = state.supersede_active_plan(
            goal="New workflow",
            steps=[make_step("New step")],
            source_user_input_summary="New.",
        )

        self.assertEqual(old_plan.status, "superseded")
        self.assertIsNone(state.active_plan)
        self.assertIs(state.pending_plan, new_plan)
        self.assertEqual(new_plan.status, "pending_confirmation")

    def test_expired_pending_plan_cannot_be_confirmed(self) -> None:
        state = PlanningState()
        pending = state.create_pending_plan(
            goal="Temporary workflow",
            steps=[make_step()],
            source_user_input_summary="Temporary.",
        )

        expired = state.expire_pending_plan()

        self.assertIs(expired, pending)
        self.assertEqual(expired.status, "expired")
        with self.assertRaises(RuntimeError):
            expired.confirm()


if __name__ == "__main__":
    unittest.main()
