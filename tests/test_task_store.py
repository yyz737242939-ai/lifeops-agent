import tempfile
import unittest
from pathlib import Path

from app.utils.json_file import read_json_file
from app.tasks.task_store import TASK_STORE_VERSION, TaskStore


class TaskStoreTests(unittest.TestCase):
    def test_missing_file_returns_empty_task_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")

            tasks = store.list_tasks()

        self.assertEqual(tasks, [])

    def test_create_task_persists_versioned_json_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            store = TaskStore(path)

            task = store.create_task(
                title="Task State v1",
                goal="Persist long-lived task state",
                steps=["Define store", "Write tests"],
                tags=["Runtime", "runtime"],
            )
            payload = read_json_file(path, dict)
            reloaded = TaskStore(path).get_task(task.id)

        self.assertEqual(payload["version"], TASK_STORE_VERSION)
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.title, "Task State v1")
        self.assertEqual(reloaded.tags, ["runtime"])
        self.assertEqual(
            [step.title for step in reloaded.steps],
            ["Define store", "Write tests"],
        )
        self.assertEqual(reloaded.current_step_id, reloaded.steps[0].id)

    def test_list_tasks_defaults_to_active_paused_and_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            active = store.create_task(title="Active", goal="Keep going")
            paused = store.create_task(title="Paused", goal="Wait")
            completed = store.create_task(title="Completed", goal="Done")

            store.update_task_status(paused.id, "paused")
            store.update_task_status(completed.id, "completed")
            visible = store.list_tasks()
            all_tasks = store.list_tasks(
                statuses={"active", "paused", "blocked", "completed", "cancelled"}
            )

        self.assertEqual([task.id for task in visible], [active.id, paused.id])
        self.assertEqual(len(all_tasks), 3)

    def test_updates_steps_notes_and_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task Store",
                goal="Persist task state",
            )

            with_step = store.add_step(task.id, "Implement store")
            assert with_step is not None
            step = with_step.steps[0]
            store.update_step(
                task.id,
                step.id,
                title="Implement JSON store",
                summary="Use versioned JSON payload",
                status="in_progress",
            )
            store.add_note(
                task.id,
                "Store API is implemented",
                related_step_id=step.id,
            )
            blocked = store.add_blocker(
                task.id,
                "Need tests",
                related_step_id=step.id,
            )
            assert blocked is not None
            blocker = blocked.blockers[0]
            store.resolve_blocker(task.id, blocker.id)
            store.complete_step(task.id, step.id)
            reloaded = TaskStore(Path(directory) / "tasks.json").get_task(task.id)

        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.status, "active")
        self.assertEqual(reloaded.steps[0].title, "Implement JSON store")
        self.assertEqual(reloaded.steps[0].summary, "Use versioned JSON payload")
        self.assertEqual(reloaded.steps[0].status, "done")
        self.assertEqual(reloaded.blockers[0].status, "resolved")
        self.assertEqual(reloaded.progress_notes[0].content, "Store API is implemented")

    def test_skip_step_clears_current_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task Store",
                goal="Persist task state",
                steps=["Optional cleanup"],
            )

            updated = store.skip_step(task.id, task.steps[0].id)

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.steps[0].status, "skipped")
        self.assertIsNone(updated.current_step_id)

    def test_missing_task_mutations_return_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")

            updated = store.update_task_status("task_missing", "paused")
            stepped = store.add_step("task_missing", "No task")

        self.assertIsNone(updated)
        self.assertIsNone(stepped)

    def test_rejects_invalid_status_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task Store",
                goal="Persist task state",
                steps=["Implement"],
            )

            with self.assertRaisesRegex(ValueError, "Unknown task status"):
                store.update_task_status(task.id, "waiting")
            with self.assertRaisesRegex(ValueError, "Unknown task step status"):
                store.update_step(task.id, task.steps[0].id, status="waiting")

    def test_rejects_unsupported_store_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            path.write_text('{"version": 999, "tasks": []}', encoding="utf-8")
            store = TaskStore(path)

            with self.assertRaisesRegex(ValueError, "Unsupported task store version"):
                store.list_tasks()


if __name__ == "__main__":
    unittest.main()
