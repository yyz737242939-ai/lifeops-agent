import tempfile
import unittest
from pathlib import Path

from app.runtime.recovery_store import (
    RUN_RECORD_STORE_VERSION,
    RunRecordStore,
)
from app.runtime.run_state import (
    ActionRecord,
    ActionStatus,
    RunState,
    StopReason,
)
from app.utils.json_file import read_json_file


class RunRecordStoreTests(unittest.TestCase):
    def test_missing_file_returns_empty_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RunRecordStore(Path(directory) / "runs.json")

            runs = store.list_recent_runs()

        self.assertEqual(runs, [])

    def test_start_run_persists_versioned_json_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            state = RunState(run_id="run-test")
            store = RunRecordStore(path)

            started = store.start_run(
                state,
                user_input_summary="Continue Recovery persistence",
                task_id="task-1",
            )
            payload = read_json_file(path, dict)
            reloaded = RunRecordStore(path).list_recent_runs()

        self.assertEqual(payload["version"], RUN_RECORD_STORE_VERSION)
        self.assertEqual(payload["runs"][0]["run_id"], "run-test")
        self.assertEqual(started.status, "running")
        self.assertEqual(reloaded[0].task_id, "task-1")

    def test_record_action_updates_counts_and_last_action_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            state = RunState(run_id="run-test")
            store = RunRecordStore(path)
            store.start_run(state, user_input_summary="Record actions")

            updated = store.record_action(
                state.run_id,
                ActionRecord(
                    call_id="call-1",
                    tool_name="list_tasks",
                    arguments={"limit": 3},
                    status=ActionStatus.COMPLETED,
                    result={"ok": True, "tasks": ["Recovery"]},
                ),
                tool_effect="read",
            )
            failed = store.record_action(
                state.run_id,
                ActionRecord(
                    call_id="call-2",
                    tool_name="add_task_note",
                    arguments={"task_id": "task-1", "content": "x" * 800},
                    status=ActionStatus.FAILED,
                    error={"ok": False, "error": "Denied"},
                    idempotency_key="idem-1",
                ),
                tool_effect="write",
            )

        assert updated is not None
        assert failed is not None
        self.assertEqual(failed.action_count, 2)
        self.assertEqual(failed.last_successful_action.tool_name, "list_tasks")
        self.assertEqual(failed.last_failed_action.tool_name, "add_task_note")
        self.assertEqual(failed.actions[1].effect, "write")
        self.assertEqual(failed.actions[1].idempotency_key, "idem-1")
        self.assertLessEqual(len(repr(failed.actions[1].arguments_preview)), 430)

    def test_finish_run_updates_terminal_status_and_stop_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            state = RunState(run_id="run-test")
            store = RunRecordStore(path)
            store.start_run(state, user_input_summary="Finish run")

            state.stop(StopReason.TOOL_BUDGET_EXHAUSTED, partial=True)
            finished = store.finish_run(state)
            reloaded = RunRecordStore(path).list_recent_runs()[0]

        assert finished is not None
        self.assertEqual(finished.status, "partial")
        self.assertEqual(finished.stop_reason, "tool_budget_exhausted")
        self.assertIsNotNone(finished.ended_at)
        self.assertEqual(reloaded.status, "partial")

    def test_mark_stale_running_as_interrupted_only_changes_running_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            store = RunRecordStore(path)
            running = RunState(run_id="run-running")
            completed = RunState(run_id="run-completed")
            store.start_run(running, user_input_summary="Still running")
            store.start_run(completed, user_input_summary="Completed")
            completed.complete()
            store.finish_run(completed)

            interrupted = store.mark_stale_running_as_interrupted()
            runs = {run.run_id: run for run in RunRecordStore(path).list_recent_runs()}

        self.assertEqual([run.run_id for run in interrupted], ["run-running"])
        self.assertEqual(runs["run-running"].status, "interrupted")
        self.assertEqual(runs["run-running"].stop_reason, "process_interrupted")
        self.assertEqual(runs["run-completed"].status, "completed")

    def test_latest_recoverable_run_ignores_completed_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RunRecordStore(Path(directory) / "runs.json")
            completed = RunState(run_id="run-completed")
            failed = RunState(run_id="run-failed")
            store.start_run(completed, user_input_summary="Completed")
            completed.complete()
            store.finish_run(completed)
            store.start_run(failed, user_input_summary="Failed")
            failed.fail(StopReason.LLM_REQUEST_FAILED)
            store.finish_run(failed)

            latest = store.get_latest_recoverable_run()

        assert latest is not None
        self.assertEqual(latest.run_id, "run-failed")

    def test_rejects_unsupported_store_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            path.write_text('{"version": 999, "runs": []}', encoding="utf-8")
            store = RunRecordStore(path)

            with self.assertRaisesRegex(
                ValueError,
                "Unsupported run record store version",
            ):
                store.list_recent_runs()


if __name__ == "__main__":
    unittest.main()
