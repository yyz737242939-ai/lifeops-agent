"""SQLite repository for durable PlanRun and PlanStep lifecycle facts."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.planning.errors import PlanRepositoryError
from app.planning.lifecycle import ready_steps, validate_plan_draft
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepStatus,
    PlanningLimits,
)


class SqlitePlanRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_initial_plan(
        self,
        *,
        session_id: str,
        goal: str,
        draft: PlanDraft,
        limits: PlanningLimits,
        plan_id: str | None = None,
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        validate_plan_draft(draft, limits)
        now = utc_now_iso()
        run = PlanRun(
            plan_id or new_id("plan"),
            session_id,
            goal,
            PlanRunStatus.AWAITING_CONFIRMATION,
            created_at=now,
            updated_at=now,
        )
        steps = _materialize_steps(run.plan_id, 1, draft)
        try:
            with self._conn:
                self._conn.execute(
                    """INSERT INTO plan_runs (
                           id, session_id, goal, status, current_revision,
                           replan_count, executor_steps_used, created_at, updated_at,
                           confirmed_at, completed_at, last_error_code,
                           confirmed_constraints_json, last_command_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    _run_values(run) + (None,),
                )
                self._insert_steps(steps)
        except sqlite3.Error as exc:
            raise _storage_failure() from exc
        return run, steps

    def get_plan(
        self, session_id: str, plan_id: str, *, recover_interrupted: bool = False
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        row = self._conn.execute("SELECT * FROM plan_runs WHERE id = ?", (plan_id,)).fetchone()
        if row is None or str(row["session_id"]) != session_id:
            raise PlanRepositoryError("Plan was not found.", code="plan_not_found")
        if recover_interrupted and str(row["status"]) == PlanRunStatus.RUNNING:
            self._mark_interrupted(plan_id)
            row = self._conn.execute("SELECT * FROM plan_runs WHERE id = ?", (plan_id,)).fetchone()
        run = _run_from_row(row)
        return run, self.list_steps(plan_id, run.current_revision)

    def list_steps(self, plan_id: str, revision: int) -> tuple[PlanStep, ...]:
        rows = self._conn.execute(
            """SELECT * FROM plan_steps
               WHERE plan_id = ? AND revision = ? ORDER BY position""",
            (plan_id, revision),
        ).fetchall()
        return tuple(_step_from_row(row) for row in rows)

    def list_completed_steps(
        self, plan_id: str, through_revision: int
    ) -> tuple[PlanStep, ...]:
        rows = self._conn.execute(
            """SELECT * FROM plan_steps
               WHERE plan_id = ? AND revision <= ? AND status = 'completed'
               ORDER BY revision, position""",
            (plan_id, through_revision),
        ).fetchall()
        return tuple(_step_from_row(row) for row in rows)

    def apply_command(
        self,
        command: PlanCommand,
        *,
        replacement_draft: PlanDraft | None = None,
        limits: PlanningLimits | None = None,
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        try:
            with self._conn:
                row = self._load_run_for_command(command)
                if row["last_command_id"] == command.command_id:
                    run = _run_from_row(row)
                    return run, self.list_steps(run.plan_id, run.current_revision)
                run = _run_from_row(row)
                if command.revision != run.current_revision:
                    raise PlanRepositoryError("Plan revision is stale.", code="plan_revision_stale")
                if command.action == PlanCommandAction.MODIFY:
                    if replacement_draft is None or limits is None:
                        raise PlanRepositoryError(
                            "Modify requires a replacement plan.", code="plan_contract_invalid"
                        )
                    validate_plan_draft(replacement_draft, limits)
                    return self._modify(run, command, replacement_draft)
                target = (
                    PlanRunStatus.RUNNING
                    if command.action == PlanCommandAction.CONFIRM
                    else PlanRunStatus.CANCELLED
                )
                allowed = {
                    PlanRunStatus.AWAITING_CONFIRMATION,
                    PlanRunStatus.AWAITING_REPLAN_CONFIRMATION,
                }
                if run.status not in allowed:
                    raise PlanRepositoryError(
                        "Plan command is not allowed.", code="plan_command_not_allowed"
                    )
                now = utc_now_iso()
                cursor = self._conn.execute(
                    """UPDATE plan_runs
                       SET status = ?, updated_at = ?, confirmed_at = ?, completed_at = ?,
                           last_command_id = ?
                       WHERE id = ? AND session_id = ? AND current_revision = ? AND status = ?""",
                    (
                        target.value,
                        now,
                        now if target == PlanRunStatus.RUNNING else run.confirmed_at,
                        now if target == PlanRunStatus.CANCELLED else None,
                        command.command_id,
                        run.plan_id,
                        run.session_id,
                        run.current_revision,
                        run.status.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PlanRepositoryError("Plan revision is stale.", code="plan_revision_stale")
                if target == PlanRunStatus.CANCELLED:
                    self._conn.execute(
                        """UPDATE plan_steps SET status = 'cancelled', completed_at = ?
                           WHERE plan_id = ? AND revision = ? AND status = 'pending'""",
                        (now, run.plan_id, run.current_revision),
                    )
        except PlanRepositoryError:
            raise
        except sqlite3.Error as exc:
            raise _storage_failure() from exc
        return self.get_plan(command.session_id, command.plan_id)

    def claim_ready_step(self, session_id: str, plan_id: str, revision: int) -> PlanStep | None:
        try:
            with self._conn:
                run, steps = self.get_plan(session_id, plan_id)
                _require_current_running(run, revision)
                candidates = ready_steps(steps)
                if not candidates:
                    return None
                step = candidates[0]
                now = utc_now_iso()
                cursor = self._conn.execute(
                    """UPDATE plan_steps SET status = 'running', started_at = ?
                       WHERE plan_id = ? AND revision = ? AND step_id = ? AND status = 'pending'""",
                    (now, plan_id, revision, step.step_id),
                )
                if cursor.rowcount != 1:
                    raise PlanRepositoryError(
                        "Plan step claim is stale.", code="plan_command_not_allowed"
                    )
        except PlanRepositoryError:
            raise
        except sqlite3.Error as exc:
            raise _storage_failure() from exc
        return replace(step, status=PlanStepStatus.RUNNING, started_at=now)

    def record_step_result(
        self,
        *,
        session_id: str,
        plan_id: str,
        revision: int,
        step_id: str,
        status: PlanStepStatus,
        executor_steps_used: int,
        limits: PlanningLimits,
        safe_result_summary: str | None = None,
        stop_reason: str | None = None,
        error_code: str | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> tuple[PlanRun, PlanStep]:
        if status not in {
            PlanStepStatus.COMPLETED,
            PlanStepStatus.GOAL_NOT_ACHIEVED,
            PlanStepStatus.STOPPED,
            PlanStepStatus.FAILED,
        }:
            raise PlanRepositoryError("Plan step result is invalid.", code="plan_contract_invalid")
        if status == PlanStepStatus.COMPLETED and not safe_result_summary:
            raise PlanRepositoryError("Completed step requires a summary.", code="plan_contract_invalid")
        if not isinstance(executor_steps_used, int) or isinstance(executor_steps_used, bool) or executor_steps_used < 0:
            raise PlanRepositoryError("Executor usage is invalid.", code="plan_contract_invalid")
        try:
            with self._conn:
                run, _ = self.get_plan(session_id, plan_id)
                _require_current_running(run, revision)
                if executor_steps_used > limits.max_executor_steps_per_plan_step or run.executor_steps_used + executor_steps_used > limits.max_total_executor_steps:
                    raise PlanRepositoryError("Plan budget is exhausted.", code="plan_budget_exhausted")
                row = self._conn.execute(
                    """SELECT * FROM plan_steps
                       WHERE plan_id = ? AND revision = ? AND step_id = ?""",
                    (plan_id, revision, step_id),
                ).fetchone()
                if row is None or str(row["status"]) != PlanStepStatus.RUNNING:
                    raise PlanRepositoryError(
                        "Plan step result is stale.", code="plan_command_not_allowed"
                    )
                now = utc_now_iso()
                step_cursor = self._conn.execute(
                    """UPDATE plan_steps SET
                           status = ?, stop_reason = ?, safe_result_summary = ?,
                           error_code = ?, evidence_refs_json = ?,
                           executor_steps_used = executor_steps_used + ?, completed_at = ?
                       WHERE plan_id = ? AND revision = ? AND step_id = ? AND status = 'running'""",
                    (
                        status.value,
                        stop_reason,
                        safe_result_summary,
                        error_code,
                        _json_tuple(evidence_refs),
                        executor_steps_used,
                        now,
                        plan_id,
                        revision,
                        step_id,
                    ),
                )
                if step_cursor.rowcount != 1:
                    raise PlanRepositoryError(
                        "Plan step result is stale.", code="plan_command_not_allowed"
                    )
                run_cursor = self._conn.execute(
                    """UPDATE plan_runs SET executor_steps_used = executor_steps_used + ?,
                           updated_at = ? WHERE id = ? AND current_revision = ?""",
                    (executor_steps_used, now, plan_id, revision),
                )
                if run_cursor.rowcount != 1:
                    raise PlanRepositoryError("Plan revision is stale.", code="plan_revision_stale")
        except PlanRepositoryError:
            raise
        except sqlite3.Error as exc:
            raise _storage_failure() from exc
        saved_run, steps = self.get_plan(session_id, plan_id)
        return saved_run, next(item for item in steps if item.step_id == step_id)

    def create_replan_revision(
        self,
        *,
        session_id: str,
        plan_id: str,
        expected_revision: int,
        draft: PlanDraft,
        limits: PlanningLimits,
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        validate_plan_draft(draft, limits)
        try:
            with self._conn:
                run, _ = self.get_plan(session_id, plan_id)
                _require_current_running(run, expected_revision)
                if run.replan_count >= limits.max_replans:
                    raise PlanRepositoryError("Replan limit is exhausted.", code="plan_replan_exhausted")
                new_revision = expected_revision + 1
                now = utc_now_iso()
                self._conn.execute(
                    """UPDATE plan_steps SET status = 'superseded', completed_at = ?
                       WHERE plan_id = ? AND revision = ? AND status = 'pending'""",
                    (now, plan_id, expected_revision),
                )
                steps = _materialize_steps(plan_id, new_revision, draft)
                self._insert_steps(steps)
                run_cursor = self._conn.execute(
                    """UPDATE plan_runs SET current_revision = ?, replan_count = replan_count + 1,
                           status = 'awaiting_replan_confirmation', updated_at = ?,
                           last_command_id = NULL
                       WHERE id = ? AND current_revision = ? AND status = 'running'""",
                    (new_revision, now, plan_id, expected_revision),
                )
                if run_cursor.rowcount != 1:
                    raise PlanRepositoryError("Plan revision is stale.", code="plan_revision_stale")
        except PlanRepositoryError:
            raise
        except sqlite3.Error as exc:
            raise _storage_failure() from exc
        return self.get_plan(session_id, plan_id)

    def finish_plan(
        self,
        session_id: str,
        plan_id: str,
        revision: int,
        status: PlanRunStatus,
        *,
        error_code: str | None = None,
    ) -> PlanRun:
        if status not in {PlanRunStatus.COMPLETED, PlanRunStatus.STOPPED, PlanRunStatus.FAILED}:
            raise PlanRepositoryError("Terminal plan status is invalid.", code="plan_contract_invalid")
        now = utc_now_iso()
        with self._conn:
            cursor = self._conn.execute(
                """UPDATE plan_runs SET status = ?, updated_at = ?, completed_at = ?,
                       last_error_code = ?
                   WHERE id = ? AND session_id = ? AND current_revision = ? AND status = 'running'""",
                (status.value, now, now, error_code, plan_id, session_id, revision),
            )
            if cursor.rowcount != 1:
                raise PlanRepositoryError("Plan revision is stale.", code="plan_revision_stale")
        return self.get_plan(session_id, plan_id)[0]

    def _load_run_for_command(self, command: PlanCommand):
        row = self._conn.execute("SELECT * FROM plan_runs WHERE id = ?", (command.plan_id,)).fetchone()
        if row is None or str(row["session_id"]) != command.session_id:
            raise PlanRepositoryError("Plan was not found.", code="plan_not_found")
        return row

    def _modify(
        self, run: PlanRun, command: PlanCommand, draft: PlanDraft
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        if run.status not in {
            PlanRunStatus.AWAITING_CONFIRMATION,
            PlanRunStatus.AWAITING_REPLAN_CONFIRMATION,
        }:
            raise PlanRepositoryError("Plan command is not allowed.", code="plan_command_not_allowed")
        now = utc_now_iso()
        self._conn.execute(
            """UPDATE plan_steps SET status = 'superseded', completed_at = ?
               WHERE plan_id = ? AND revision = ? AND status = 'pending'""",
            (now, run.plan_id, run.current_revision),
        )
        new_revision = run.current_revision + 1
        confirmed_constraints = run.confirmed_constraints
        if command.feedback not in confirmed_constraints:
            confirmed_constraints = (*confirmed_constraints, command.feedback)
        self._insert_steps(_materialize_steps(run.plan_id, new_revision, draft))
        run_cursor = self._conn.execute(
            """UPDATE plan_runs SET current_revision = ?, updated_at = ?, last_command_id = ?,
                   confirmed_constraints_json = ?
               WHERE id = ? AND current_revision = ? AND status = ?""",
            (
                new_revision,
                now,
                command.command_id,
                _json_tuple(confirmed_constraints),
                run.plan_id,
                run.current_revision,
                run.status.value,
            ),
        )
        if run_cursor.rowcount != 1:
            raise PlanRepositoryError("Plan revision is stale.", code="plan_revision_stale")
        updated = replace(
            run,
            current_revision=new_revision,
            updated_at=now,
            confirmed_constraints=confirmed_constraints,
        )
        return updated, self.list_steps(run.plan_id, new_revision)

    def _mark_interrupted(self, plan_id: str) -> None:
        now = utc_now_iso()
        with self._conn:
            self._conn.execute(
                """UPDATE plan_steps SET status = 'stopped', stop_reason = ?, completed_at = ?
                   WHERE plan_id = ? AND status = 'running'""",
                ("plan_execution_interrupted", now, plan_id),
            )
            self._conn.execute(
                """UPDATE plan_runs SET status = 'stopped', updated_at = ?, completed_at = ?,
                       last_error_code = 'plan_execution_interrupted'
                   WHERE id = ? AND status = 'running'""",
                (now, now, plan_id),
            )

    def _insert_steps(self, steps: tuple[PlanStep, ...]) -> None:
        self._conn.executemany(
            """INSERT INTO plan_steps (
                   plan_id, revision, step_id, position, objective, expected_outcome,
                   dependency_step_ids_json, status, stop_reason, safe_result_summary,
                   error_code, evidence_refs_json, executor_steps_used, started_at, completed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_step_values(step) for step in steps),
        )


def _require_current_running(run: PlanRun, revision: int) -> None:
    if revision != run.current_revision:
        raise PlanRepositoryError("Plan revision is stale.", code="plan_revision_stale")
    if run.status != PlanRunStatus.RUNNING:
        raise PlanRepositoryError("Plan command is not allowed.", code="plan_command_not_allowed")


def _materialize_steps(plan_id: str, revision: int, draft: PlanDraft) -> tuple[PlanStep, ...]:
    return tuple(
        PlanStep(
            plan_id,
            revision,
            item.step_id,
            item.position,
            item.objective,
            item.expected_outcome,
            item.dependency_step_ids,
            PlanStepStatus.PENDING,
        )
        for item in draft.steps
    )


def _run_values(run: PlanRun) -> tuple[object, ...]:
    return (
        run.plan_id,
        run.session_id,
        run.goal,
        run.status.value,
        run.current_revision,
        run.replan_count,
        run.executor_steps_used,
        run.created_at,
        run.updated_at,
        run.confirmed_at,
        run.completed_at,
        run.last_error_code,
        _json_tuple(run.confirmed_constraints),
    )


def _step_values(step: PlanStep) -> tuple[object, ...]:
    return (
        step.plan_id,
        step.revision,
        step.step_id,
        step.position,
        step.objective,
        step.expected_outcome,
        _json_tuple(step.dependency_step_ids),
        step.status.value,
        step.stop_reason,
        step.safe_result_summary,
        step.error_code,
        _json_tuple(step.evidence_refs),
        step.executor_steps_used,
        step.started_at,
        step.completed_at,
    )


def _run_from_row(row) -> PlanRun:
    return PlanRun(
        str(row["id"]),
        str(row["session_id"]),
        str(row["goal"]),
        PlanRunStatus(str(row["status"])),
        int(row["current_revision"]),
        int(row["replan_count"]),
        int(row["executor_steps_used"]),
        str(row["created_at"]),
        str(row["updated_at"]),
        str(row["confirmed_at"]) if row["confirmed_at"] is not None else None,
        str(row["completed_at"]) if row["completed_at"] is not None else None,
        str(row["last_error_code"]) if row["last_error_code"] is not None else None,
        _read_string_tuple(row["confirmed_constraints_json"]),
    )


def _step_from_row(row) -> PlanStep:
    return PlanStep(
        str(row["plan_id"]),
        int(row["revision"]),
        str(row["step_id"]),
        int(row["position"]),
        str(row["objective"]),
        str(row["expected_outcome"]),
        _read_string_tuple(row["dependency_step_ids_json"]),
        PlanStepStatus(str(row["status"])),
        str(row["stop_reason"]) if row["stop_reason"] is not None else None,
        str(row["safe_result_summary"]) if row["safe_result_summary"] is not None else None,
        str(row["error_code"]) if row["error_code"] is not None else None,
        _read_string_tuple(row["evidence_refs_json"]),
        int(row["executor_steps_used"]),
        str(row["started_at"]) if row["started_at"] is not None else None,
        str(row["completed_at"]) if row["completed_at"] is not None else None,
    )


def _json_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _read_string_tuple(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise PlanRepositoryError("Stored plan JSON is invalid.", code="plan_contract_invalid") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise PlanRepositoryError("Stored plan JSON is invalid.", code="plan_contract_invalid")
    return tuple(parsed)


def _storage_failure() -> PlanRepositoryError:
    return PlanRepositoryError("Plan repository operation failed.", code="plan_repository_failed")
