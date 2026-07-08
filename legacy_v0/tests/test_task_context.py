from pathlib import Path
import tempfile
import unittest

from app.tasks.task_context import TaskContextBuilder
from app.tasks.task_store import TaskStore


class TaskContextBuilderTests(unittest.TestCase):
    def test_current_task_cue_selects_latest_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            old_task = store.create_task(
                title="Old Task",
                goal="Earlier task",
                steps=["Old step"],
            )
            latest_task = store.create_task(
                title="Task State v1",
                goal="Build task context",
                steps=["Inject task context"],
            )
            builder = TaskContextBuilder(store)

            result = builder.build("继续上次任务")
            message = result.message()

        self.assertEqual([task.id for task in result.tasks], [latest_task.id])
        self.assertEqual(result.reason, "latest_active_task")
        self.assertIsNotNone(message)
        assert message is not None
        self.assertIn("Current task context", message["content"])
        self.assertIn(latest_task.id, message["content"])
        self.assertNotIn(old_task.id, message["content"])
        self.assertIn("Inject task context", message["content"])

    def test_task_id_selects_exact_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task State v1",
                goal="Build task context",
            )
            builder = TaskContextBuilder(store)

            result = builder.build(f"查看任务 {task.id}")

        self.assertEqual([item.id for item in result.tasks], [task.id])
        self.assertEqual(result.reason, "task_id")

    def test_keyword_match_with_multiple_candidates_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            first = store.create_task(
                title="Task State implementation",
                goal="Build task runtime",
                tags=["runtime"],
            )
            second = store.create_task(
                title="Runtime docs",
                goal="Document task runtime",
                tags=["runtime"],
            )
            builder = TaskContextBuilder(store)

            result = builder.build("runtime 任务有哪些？")
            message = result.message()

        self.assertTrue(result.ambiguous)
        self.assertEqual({task.id for task in result.tasks}, {first.id, second.id})
        self.assertIsNotNone(message)
        assert message is not None
        self.assertIn("Task candidates", message["content"])
        self.assertIn("choose one by id", message["content"])

    def test_no_task_cue_does_not_inject_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            store.create_task(title="Task State v1", goal="Build task context")
            builder = TaskContextBuilder(store)

            result = builder.build("今天怎么安排学习？")

        self.assertFalse(result.injected)
        self.assertIsNone(result.message())
        self.assertEqual(result.reason, "no_task_context_cue")

    def test_completed_tasks_are_not_used_for_current_task_cue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(title="Done Task", goal="Already done")
            store.update_task_status(task.id, "completed")
            builder = TaskContextBuilder(store)

            result = builder.build("继续上次任务")

        self.assertFalse(result.injected)
        self.assertEqual(result.reason, "no_active_tasks")


if __name__ == "__main__":
    unittest.main()
