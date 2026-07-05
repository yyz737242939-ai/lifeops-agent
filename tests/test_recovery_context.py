import tempfile
import unittest
from pathlib import Path

from app.runtime.recovery_context import RecoveryContextBuilder
from app.runtime.recovery_store import RunRecordStore
from app.runtime.run_state import ActionRecord, ActionStatus, RunState, StopReason
from app.tasks.task_context import TaskContextBuilder
from app.tasks.task_store import TaskStore


class RecoveryContextBuilderTests(unittest.TestCase):
    def test_recovery_cue_selects_single_recoverable_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RunRecordStore(Path(directory) / "runs.json")
            state = RunState(run_id="run-partial")
            store.start_run(state, user_input_summary="Continue Recovery")
            store.record_action(
                state.run_id,
                ActionRecord(
                    call_id="call-1",
                    tool_name="list_tasks",
                    arguments={},
                    status=ActionStatus.COMPLETED,
                    result={"ok": True},
                ),
                tool_effect="read",
            )
            state.stop(StopReason.LLM_REQUEST_FAILED, partial=True)
            store.finish_run(state)
            builder = RecoveryContextBuilder(store)

            result = builder.build("继续刚才")
            message = result.message()

        self.assertTrue(result.injected)
        self.assertEqual(result.reason, "latest_recoverable_run")
        self.assertIsNotNone(message)
        assert message is not None
        self.assertIn("Recent recovery context", message["content"])
        self.assertIn("run-partial", message["content"])
        self.assertIn("Do not replay tools automatically", message["content"])

    def test_multiple_recoverable_runs_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RunRecordStore(Path(directory) / "runs.json")
            for run_id in ("run-one", "run-two"):
                state = RunState(run_id=run_id)
                store.start_run(state, user_input_summary=run_id)
                state.fail(StopReason.LLM_REQUEST_FAILED)
                store.finish_run(state)
            builder = RecoveryContextBuilder(store)

            result = builder.build("上次失败在哪")
            message = result.message()

        self.assertTrue(result.ambiguous)
        self.assertEqual(result.reason, "multiple_recoverable_runs")
        self.assertIsNotNone(message)
        assert message is not None
        self.assertIn("Recovery candidates", message["content"])
        self.assertIn("choose one by run_id", message["content"])

    def test_task_context_selects_related_recoverable_run_without_generic_cue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_store = TaskStore(Path(directory) / "tasks.json")
            task = task_store.create_task(
                title="Recovery work",
                goal="Build context injection",
            )
            run_store = RunRecordStore(Path(directory) / "runs.json")
            unrelated = RunState(run_id="run-unrelated")
            run_store.start_run(unrelated, user_input_summary="Other")
            unrelated.fail(StopReason.LLM_REQUEST_FAILED)
            run_store.finish_run(unrelated)
            related = RunState(run_id="run-related")
            run_store.start_run(
                related,
                user_input_summary="Task run",
                task_id=task.id,
            )
            related.stop(StopReason.LLM_REQUEST_FAILED, partial=True)
            run_store.finish_run(related)
            task_context = TaskContextBuilder(task_store).build("继续上次任务")
            builder = RecoveryContextBuilder(run_store)

            result = builder.build("继续上次任务", task_context=task_context)

        self.assertEqual([run.run_id for run in result.runs], ["run-related"])
        self.assertEqual(result.reason, "task_related_recoverable_run")

    def test_no_recovery_cue_does_not_inject_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RunRecordStore(Path(directory) / "runs.json")
            state = RunState(run_id="run-failed")
            store.start_run(state, user_input_summary="Failed")
            state.fail(StopReason.LLM_REQUEST_FAILED)
            store.finish_run(state)
            builder = RecoveryContextBuilder(store)

            result = builder.build("今天怎么安排学习？")

        self.assertFalse(result.injected)
        self.assertEqual(result.reason, "no_recovery_cue")
        self.assertIsNone(result.message())


if __name__ == "__main__":
    unittest.main()
