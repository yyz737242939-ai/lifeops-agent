"""JSON-backed Runtime Recovery store."""

from pathlib import Path
from typing import Any

from app.runtime.recovery_types import (
    PersistentActionRecord,
    RecoveryActionEffect,
    RunRecord,
)
from app.runtime.run_state import ActionRecord, ActionStatus, RunState, stable_signature
from app.utils.json_file import read_json_file, write_json_file
from app.utils.time import now_iso


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RECOVERY_DIR = DATA_DIR / "recovery"
RUN_RECORDS_FILE = RECOVERY_DIR / "runs.json"
RUN_RECORD_STORE_VERSION = 1
RECOVERABLE_RUN_STATUSES = {"interrupted", "partial", "failed"}
SUMMARY_LIMIT = 240
PREVIEW_LIMIT = 400


class RunRecordStore:
    """Persistent run records used to explain interrupted or partial work."""

    def __init__(self, path: str | Path = RUN_RECORDS_FILE) -> None:
        self.path = Path(path)

    def start_run(
        self,
        run_state: RunState,
        *,
        user_input_summary: str,
        task_id: str | None = None,
    ) -> RunRecord:
        runs = self._load()
        if self._find_run(runs, run_state.run_id) is not None:
            raise ValueError("Run record already exists")

        now = now_iso()
        run = RunRecord(
            run_id=run_state.run_id,
            status=run_state.status.value,
            started_at=now,
            task_id=task_id,
            plan_id=run_state.plan_id,
            plan_step_id=run_state.plan_step_id,
            user_input_summary=_summarize_text(user_input_summary),
            created_at=now,
            updated_at=now,
        )
        runs.append(run)
        self._save(runs)
        return run

    def record_action(
        self,
        run_id: str,
        action_record: ActionRecord,
        *,
        tool_effect: RecoveryActionEffect,
        plan_id: str | None = None,
        plan_step_id: str | None = None,
    ) -> RunRecord | None:
        runs = self._load()
        run = self._find_run(runs, run_id)
        if run is None:
            return None

        now = now_iso()
        if plan_id is not None:
            run.plan_id = plan_id
        if plan_step_id is not None:
            run.plan_step_id = plan_step_id
        action = _persistent_action_from_record(
            run_id,
            action_record,
            tool_effect=tool_effect,
            timestamp=now,
        )
        run.actions.append(action)
        run.action_count = len(run.actions)
        if action.status == "completed":
            run.last_successful_action = action
        elif action.status == "failed":
            run.last_failed_action = action
        run.updated_at = now
        self._save(runs)
        return run

    def finish_run(self, run_state: RunState) -> RunRecord | None:
        runs = self._load()
        run = self._find_run(runs, run_state.run_id)
        if run is None:
            return None

        now = now_iso()
        run.status = run_state.status.value
        run.ended_at = now
        run.stop_reason = run_state.stop_reason.value if run_state.stop_reason else None
        run.plan_id = run_state.plan_id
        run.plan_step_id = run_state.plan_step_id
        run.action_count = len(run.actions)
        run.updated_at = now
        self._save(runs)
        return run

    def mark_stale_running_as_interrupted(self) -> list[RunRecord]:
        runs = self._load()
        interrupted: list[RunRecord] = []
        now = now_iso()
        for run in runs:
            if run.status != "running":
                continue
            run.status = "interrupted"
            run.ended_at = now
            run.stop_reason = "process_interrupted"
            run.updated_at = now
            interrupted.append(run)
        if interrupted:
            self._save(runs)
        return interrupted

    def get_latest_recoverable_run(self) -> RunRecord | None:
        for run in self.list_recent_runs(limit=None):
            if run.status in RECOVERABLE_RUN_STATUSES:
                return run
        return None

    def list_recent_runs(self, limit: int | None = 10) -> list[RunRecord]:
        runs = list(reversed(self._load()))
        if limit is None:
            return runs
        if limit < 1:
            return []
        return runs[:limit]

    def _load(self) -> list[RunRecord]:
        if not self.path.exists():
            return []

        payload = read_json_file(self.path, dict)
        version = payload.get("version")
        if version != RUN_RECORD_STORE_VERSION:
            raise ValueError(f"Unsupported run record store version: {version}")

        raw_runs = payload.get("runs")
        if not isinstance(raw_runs, list):
            raise ValueError(f"{self.path} must contain a JSON runs list")
        return [RunRecord.from_dict(item) for item in raw_runs]

    def _save(self, runs: list[RunRecord]) -> None:
        payload: dict[str, Any] = {
            "version": RUN_RECORD_STORE_VERSION,
            "runs": [run.to_dict() for run in runs],
        }
        write_json_file(self.path, payload)

    @staticmethod
    def _find_run(runs: list[RunRecord], run_id: str) -> RunRecord | None:
        return next((run for run in runs if run.run_id == run_id), None)


def _persistent_action_from_record(
    run_id: str,
    action_record: ActionRecord,
    *,
    tool_effect: RecoveryActionEffect,
    timestamp: str,
) -> PersistentActionRecord:
    return PersistentActionRecord(
        run_id=run_id,
        call_id=action_record.call_id,
        tool_name=action_record.tool_name,
        arguments_hash=stable_signature(action_record.arguments),
        arguments_preview=_preview_arguments(action_record.arguments),
        status=_recovery_action_status(action_record.status),
        effect=tool_effect,
        idempotency_key=action_record.idempotency_key,
        result_summary=_summarize_value(action_record.result),
        error_summary=_summarize_value(action_record.error),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _recovery_action_status(status: ActionStatus) -> str:
    return status.value


def _preview_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        preview = _bounded_value(arguments, limit=PREVIEW_LIMIT)
        return preview if isinstance(preview, dict) else {"preview": preview}
    return {"preview": _summarize_value(arguments, limit=PREVIEW_LIMIT)}


def _summarize_value(value: Any, *, limit: int = SUMMARY_LIMIT) -> str | None:
    if value is None:
        return None
    return _summarize_text(repr(value), limit=limit)


def _summarize_text(value: str, *, limit: int = SUMMARY_LIMIT) -> str:
    clean_value = " ".join(value.strip().split())
    if len(clean_value) <= limit:
        return clean_value
    return f"{clean_value[: limit - 3]}..."


def _bounded_value(value: Any, *, limit: int) -> Any:
    preview = repr(value)
    if len(preview) <= limit:
        return value
    return _summarize_text(preview, limit=limit)
