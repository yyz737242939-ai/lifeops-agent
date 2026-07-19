import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.tasks.task_store import TaskStore
from app.tools.capability_builder import build_capabilities
from app.tools.tool import call_tool


class TaskToolTests(unittest.TestCase):
    def test_create_task_tool_persists_only_when_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            capability = build_capabilities(
                (),
                authorized_write_tool_names=frozenset({"create_task"}),
            )

            with patch("app.tools.tool.task_store", store):
                result = json.loads(
                    call_tool(
                        "create_task",
                        {
                            "title": "Task State v1",
                            "goal": "Expose Task tools safely",
                            "steps": ["Register tools"],
                            "tags": ["runtime"],
                        },
                        allowed_tool_names=capability.allowed_tool_names,
                    )
                )
                stored = store.list_tasks()

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "create_task")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].title, "Task State v1")

    def test_denied_create_task_does_not_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            capability = build_capabilities(())

            with patch("app.tools.tool.task_store", store):
                result = json.loads(
                    call_tool(
                        "create_task",
                        {
                            "title": "Task State v1",
                            "goal": "Should not save without authorization",
                        },
                        allowed_tool_names=capability.allowed_tool_names,
                    )
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool_not_allowed")
        self.assertEqual(store.list_tasks(), [])

    def test_list_get_and_update_task_tools_use_store_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            task = store.create_task(
                title="Task State v1",
                goal="Expose Task tools safely",
                steps=["Register tools"],
                tags=["runtime"],
            )
            read_capability = build_capabilities(())
            write_capability = build_capabilities(
                (),
                authorized_write_tool_names=frozenset(
                    {
                        "add_task_step",
                        "update_task_step",
                        "set_current_task_step",
                        "add_task_note",
                        "add_task_blocker",
                        "resolve_task_blocker",
                        "update_task_status",
                    }
                ),
            )

            with patch("app.tools.tool.task_store", store):
                listed = json.loads(
                    call_tool(
                        "list_tasks",
                        {"tag": "runtime"},
                        allowed_tool_names=read_capability.allowed_tool_names,
                    )
                )
                fetched = json.loads(
                    call_tool(
                        "get_task",
                        {"task_id": task.id},
                        allowed_tool_names=read_capability.allowed_tool_names,
                    )
                )
                stepped = json.loads(
                    call_tool(
                        "add_task_step",
                        {"task_id": task.id, "title": "Write tests"},
                        allowed_tool_names=write_capability.allowed_tool_names,
                    )
                )
                new_step_id = stepped["task"]["steps"][-1]["id"]
                current = json.loads(
                    call_tool(
                        "set_current_task_step",
                        {"task_id": task.id, "step_id": new_step_id},
                        allowed_tool_names=write_capability.allowed_tool_names,
                    )
                )
                updated_step = json.loads(
                    call_tool(
                        "update_task_step",
                        {
                            "task_id": task.id,
                            "step_id": new_step_id,
                            "status": "done",
                        },
                        allowed_tool_names=write_capability.allowed_tool_names,
                    )
                )
                noted = json.loads(
                    call_tool(
                        "add_task_note",
                        {"task_id": task.id, "content": "Task tools are wired."},
                        allowed_tool_names=write_capability.allowed_tool_names,
                    )
                )
                blocked = json.loads(
                    call_tool(
                        "add_task_blocker",
                        {"task_id": task.id, "reason": "Need doc sync"},
                        allowed_tool_names=write_capability.allowed_tool_names,
                    )
                )
                blocker_id = blocked["task"]["blockers"][0]["id"]
                resolved = json.loads(
                    call_tool(
                        "resolve_task_blocker",
                        {"task_id": task.id, "blocker_id": blocker_id},
                        allowed_tool_names=write_capability.allowed_tool_names,
                    )
                )
                completed = json.loads(
                    call_tool(
                        "update_task_status",
                        {"task_id": task.id, "status": "completed"},
                        allowed_tool_names=write_capability.allowed_tool_names,
                    )
                )

        self.assertEqual(listed["count"], 1)
        self.assertEqual(fetched["task"]["id"], task.id)
        self.assertEqual(current["task"]["current_step_id"], new_step_id)
        self.assertEqual(updated_step["task"]["steps"][-1]["status"], "done")
        self.assertEqual(noted["task"]["progress_notes"][0]["content"], "Task tools are wired.")
        self.assertEqual(resolved["task"]["blockers"][0]["status"], "resolved")
        self.assertEqual(completed["task"]["status"], "completed")

    def test_missing_task_write_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(Path(directory) / "tasks.json")
            capability = build_capabilities(
                (),
                authorized_write_tool_names=frozenset({"update_task_status"}),
            )

            with patch("app.tools.tool.task_store", store):
                result = json.loads(
                    call_tool(
                        "update_task_status",
                        {"task_id": "task_missing", "status": "paused"},
                        allowed_tool_names=capability.allowed_tool_names,
                    )
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "task_not_found")


if __name__ == "__main__":
    unittest.main()
