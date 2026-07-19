from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    ToolObservation,
)
from app.planning.models import PlanRun, PlanRunStatus, PlanStep, PlanStepStatus
from app.recovery.builder import (
    DirectExecutionFacts,
    ExecutionFeedbackBuilder,
    PlanExecutorInvocationFacts,
    PlanningExecutionFacts,
    ToolEffectBinding,
)
from app.recovery.errors import ExecutionFeedbackRepositoryError
from app.recovery.models import FinalAnswerDraft
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.recovery.validator import FinalAnswerValidator
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.models import ExecutionEvidence, ToolCallStatus, ToolEffect
from tests.helpers import create_test_connection, insert_test_run_record


NOW = "2026-07-17T00:00:00Z"


class ExecutionFeedbackRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        insert_test_run_record(self.conn)
        self.repository = SqliteExecutionFeedbackRepository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_direct_round_trip_preserves_safe_actions_and_evidence(self) -> None:
        feedback = _direct_feedback()

        self.repository.save(feedback)

        self.assertEqual(self.repository.get_for_run("session_1", "run_1"), feedback)
        self.assertEqual(self.repository.get_latest("session_1"), feedback)
        row = self.conn.execute(
            "SELECT * FROM execution_feedback_actions WHERE feedback_id = ?",
            (feedback.feedback_id,),
        ).fetchone()
        self.assertEqual(row["source_span_id"], "span_1")
        self.assertEqual(row["tool_effect"], "write")
        self.assertNotIn("output", row.keys())

    def test_exact_retry_is_idempotent_but_conflict_fails_closed(self) -> None:
        feedback = _direct_feedback()
        self.repository.save(feedback)

        self.repository.save(feedback)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS count FROM execution_feedback").fetchone()[
                "count"
            ],
            1,
        )
        with self.assertRaises(ExecutionFeedbackRepositoryError) as caught:
            self.repository.save(replace(feedback, goal_summary="different safe goal"))
        self.assertEqual(caught.exception.code, "execution_feedback_source_conflict")

    def test_unknown_and_cross_session_reads_share_unavailable_failure(self) -> None:
        self.repository.save(_direct_feedback())

        for session_id, run_id in (("other_session", "run_1"), ("session_1", "missing")):
            with self.subTest(session_id=session_id, run_id=run_id):
                with self.assertRaises(ExecutionFeedbackRepositoryError) as caught:
                    self.repository.get_for_run(session_id, run_id)
                self.assertEqual(caught.exception.code, "recovery_source_unavailable")

    def test_corrupt_durable_json_is_a_safe_persistence_failure(self) -> None:
        self.repository.save(_direct_feedback())
        self.conn.execute(
            "UPDATE execution_feedback SET executor_invocation_ids_json = 'not-json'"
        )
        self.conn.commit()

        with self.assertRaises(ExecutionFeedbackRepositoryError) as caught:
            self.repository.get_for_run("session_1", "run_1")
        self.assertEqual(caught.exception.code, "execution_feedback_persistence_failed")

    def test_planning_round_trip_reuses_canonical_plan_rows(self) -> None:
        feedback, plan_run, plan_steps = _planning_feedback()
        _insert_plan(self.conn, plan_run, plan_steps)

        self.repository.save(feedback)
        loaded = self.repository.get_for_run("session_1", "run_1")

        self.assertEqual(loaded, feedback)
        self.assertEqual(loaded.plan_steps, feedback.plan_steps)
        tables = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'execution_feedback%'"
            )
        }
        self.assertEqual(
            tables,
            {
                "execution_feedback",
                "execution_feedback_actions",
                "execution_feedback_evidence",
                "execution_feedback_plan_steps",
            },
        )

    def test_planning_feedback_keeps_historical_step_snapshot(self) -> None:
        feedback, plan_run, plan_steps = _planning_feedback()
        _insert_plan(self.conn, plan_run, plan_steps)
        self.repository.save(feedback)

        self.conn.execute(
            """UPDATE plan_steps
               SET status = 'stopped', stop_reason = 'goal_not_achieved',
                   safe_result_summary = NULL, error_code = 'later_change'
               WHERE plan_id = 'plan_1' AND revision = 1 AND step_id = 'read'"""
        )
        self.conn.commit()

        loaded = self.repository.get_for_run("session_1", "run_1")
        self.assertEqual(loaded, feedback)
        self.assertEqual(loaded.plan_steps[0].outcome.value, "completed")

    def test_planning_save_rejects_feedback_that_disagrees_with_plan_owner(self) -> None:
        feedback, plan_run, plan_steps = _planning_feedback()
        changed = replace(plan_steps[0], safe_result_summary="different canonical summary")
        _insert_plan(self.conn, plan_run, (changed,))

        with self.assertRaises(ExecutionFeedbackRepositoryError) as caught:
            self.repository.save(feedback)
        self.assertEqual(caught.exception.code, "execution_feedback_source_conflict")

    def test_file_backed_feedback_survives_restart(self) -> None:
        self.conn.close()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "lifeops.db"
            first = connect_sqlite(path)
            migrate(first)
            insert_test_run_record(first)
            feedback = _direct_feedback()
            SqliteExecutionFeedbackRepository(first).save(feedback)
            first.close()

            reopened = connect_sqlite(path)
            migrate(reopened)
            try:
                loaded = SqliteExecutionFeedbackRepository(reopened).get_for_run(
                    "session_1", "run_1"
                )
            finally:
                reopened.close()
        self.conn = create_test_connection()

        self.assertEqual(loaded, feedback)


def _direct_feedback():
    observation = ToolObservation(
        1,
        "call_1",
        "research.save_source",
        ToolCallStatus.SUCCEEDED,
        evidence=(ExecutionEvidence("write_effect", "Saved.", "source/ref_1"),),
    )
    result = ExecutorResult(
        "run_1",
        ExecutorStatus.COMPLETED,
        ExecutorStopReason.FINAL_ANSWER,
        "done",
        2,
        (observation,),
    )
    feedback = ExecutionFeedbackBuilder().from_direct(
        DirectExecutionFacts(
            "feedback_1",
            "trace_1",
            "run_1",
            "session_1",
            "Save a source.",
            NOW,
            result,
            "execinv_1",
            "span_1",
            tool_effects=(
                ToolEffectBinding("research.save_source", ToolEffect.WRITE),
            ),
        )
    )
    validated = FinalAnswerValidator().validate(FinalAnswerDraft("done"), feedback)
    return replace(feedback, validation=validated.validation)


def _planning_feedback():
    plan_run = PlanRun(
        "plan_1",
        "session_1",
        "Read a source.",
        PlanRunStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        confirmed_at=NOW,
        completed_at=NOW,
    )
    step = PlanStep(
        "plan_1",
        1,
        "read",
        1,
        "Read source",
        "Source read",
        (),
        PlanStepStatus.COMPLETED,
        safe_result_summary="Read complete.",
        executor_steps_used=1,
        started_at=NOW,
        completed_at=NOW,
    )
    result = ExecutorResult(
        "run_1",
        ExecutorStatus.COMPLETED,
        ExecutorStopReason.FINAL_ANSWER,
        "done",
        1,
    )
    feedback = ExecutionFeedbackBuilder().from_plan(
        PlanningExecutionFacts(
            "feedback_1",
            "trace_1",
            "run_1",
            "session_1",
            "Read a source.",
            NOW,
            plan_run,
            (step,),
            (PlanExecutorInvocationFacts("execinv_1", "span_1", 1, "read", result),),
        )
    )
    validated = FinalAnswerValidator().validate(FinalAnswerDraft("done"), feedback)
    return replace(feedback, validation=validated.validation), plan_run, (step,)


def _insert_plan(conn, plan_run: PlanRun, steps: tuple[PlanStep, ...]) -> None:
    conn.execute(
        """INSERT INTO plan_runs (
               id, session_id, goal, status, current_revision, replan_count,
               executor_steps_used, created_at, updated_at, confirmed_at,
               completed_at, last_error_code, last_command_id,
               confirmed_constraints_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '[]')""",
        (
            plan_run.plan_id,
            plan_run.session_id,
            plan_run.goal,
            plan_run.status.value,
            plan_run.current_revision,
            plan_run.replan_count,
            plan_run.executor_steps_used,
            plan_run.created_at,
            plan_run.updated_at,
            plan_run.confirmed_at,
            plan_run.completed_at,
            plan_run.last_error_code,
        ),
    )
    conn.executemany(
        """INSERT INTO plan_steps (
               plan_id, revision, step_id, position, objective, expected_outcome,
               dependency_step_ids_json, status, stop_reason, safe_result_summary,
               error_code, evidence_refs_json, executor_steps_used, started_at,
               completed_at
           ) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, '[]', ?, ?, ?)""",
        (
            (
                step.plan_id,
                step.revision,
                step.step_id,
                step.position,
                step.objective,
                step.expected_outcome,
                step.status.value,
                step.stop_reason,
                step.safe_result_summary,
                step.error_code,
                step.executor_steps_used,
                step.started_at,
                step.completed_at,
            )
            for step in steps
        ),
    )
    conn.commit()


if __name__ == "__main__":
    unittest.main()
