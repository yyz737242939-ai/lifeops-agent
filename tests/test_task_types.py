import unittest

from app.tasks.task_types import (
    TaskBlocker,
    TaskItem,
    TaskStep,
)


class TaskStepTests(unittest.TestCase):
    def test_step_lifecycle_reaches_terminal_status(self) -> None:
        step = TaskStep(title="Write task types")

        step.start()
        step.complete()

        self.assertEqual(step.status, "done")
        self.assertIsNotNone(step.completed_at)
        with self.assertRaises(RuntimeError):
            step.block()

    def test_step_requires_title(self) -> None:
        with self.assertRaises(ValueError):
            TaskStep(title=" ")


class TaskBlockerTests(unittest.TestCase):
    def test_blocker_resolves_once(self) -> None:
        blocker = TaskBlocker(reason="Need boundary decision")

        blocker.resolve()

        self.assertEqual(blocker.status, "resolved")
        self.assertIsNotNone(blocker.resolved_at)
        with self.assertRaises(RuntimeError):
            blocker.resolve()


class TaskItemTests(unittest.TestCase):
    def test_create_task_normalizes_tags_and_serializes_json_safe_shape(self) -> None:
        task = TaskItem(
            title="Task State v1",
            goal="Build long-lived task state",
            tags=["Runtime", " runtime ", "", "Learning"],
        )

        serialized = task.to_dict()

        self.assertTrue(task.id.startswith("task_"))
        self.assertEqual(task.status, "active")
        self.assertEqual(task.source, "user_authorized")
        self.assertEqual(task.tags, ["runtime", "learning"])
        self.assertEqual(serialized["status"], "active")
        self.assertEqual(serialized["steps"], [])

    def test_add_step_sets_current_step_and_complete_step_clears_it(self) -> None:
        task = TaskItem(
            title="Task State v1",
            goal="Build long-lived task state",
        )

        step = task.add_step("Define task models")
        completed = task.complete_step(step.id)

        self.assertIs(completed, step)
        self.assertEqual(step.status, "done")
        self.assertIsNone(task.current_step_id)

    def test_set_current_step_requires_existing_step(self) -> None:
        task = TaskItem(
            title="Task State v1",
            goal="Build long-lived task state",
        )

        with self.assertRaises(ValueError):
            task.set_current_step("step_missing")

    def test_blocker_marks_task_blocked_and_resolution_restores_active(self) -> None:
        task = TaskItem(
            title="Task State v1",
            goal="Build long-lived task state",
        )
        step = task.add_step("Implement model tests")

        blocker = task.add_blocker(
            "Need to decide status lifecycle",
            related_step_id=step.id,
        )
        resolved = task.resolve_blocker(blocker.id)

        self.assertEqual(step.status, "blocked")
        self.assertEqual(blocker.status, "resolved")
        self.assertIs(resolved, blocker)
        self.assertEqual(task.status, "active")

    def test_pause_resume_complete_and_cancel_are_terminal_boundaries(self) -> None:
        task = TaskItem(
            title="Task State v1",
            goal="Build long-lived task state",
        )

        task.pause()
        self.assertEqual(task.status, "paused")
        task.resume()
        self.assertEqual(task.status, "active")
        task.complete_task()

        self.assertEqual(task.status, "completed")
        self.assertIsNotNone(task.completed_at)
        with self.assertRaises(RuntimeError):
            task.add_note("Should not mutate terminal task")

        cancelled = TaskItem(
            title="Discard old task",
            goal="Cancel obsolete task state work",
        )
        cancelled.cancel()
        with self.assertRaises(RuntimeError):
            cancelled.resume()

    def test_current_step_id_must_reference_existing_step_on_model_creation(self) -> None:
        with self.assertRaises(ValueError):
            TaskItem(
                title="Task State v1",
                goal="Build long-lived task state",
                current_step_id="step_missing",
            )


if __name__ == "__main__":
    unittest.main()
