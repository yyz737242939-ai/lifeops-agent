import json
import unittest
from unittest.mock import patch

from app.context.context_manager import (
    compact_tool_output,
    summarize_context_messages,
)


def _todo(todo_id: int) -> dict[str, object]:
    return {
        "id": todo_id,
        "title": f"Task {todo_id}",
        "status": "todo",
        "priority": "medium",
        "due_date": None,
    }


class ContextManagerTests(unittest.TestCase):
    def test_small_result_stays_inline(self) -> None:
        original = json.dumps(
            {"ok": True, "action": "get_current_time", "value": "now"}
        )

        compacted, metadata = compact_tool_output("get_current_time", original)

        self.assertEqual(compacted, original)
        self.assertEqual(metadata["strategy"], "none")

    def test_medium_list_uses_domain_summary_with_recovery_ref(self) -> None:
        result = {
            "ok": True,
            "action": "list_todos",
            "todos": [_todo(i) for i in range(9)],
        }
        original = json.dumps(result)

        with patch(
            "app.context.context_manager.save_context_ref", return_value="ctx_test"
        ) as save_ref:
            compacted, metadata = compact_tool_output("list_todos", original)
        payload = json.loads(compacted)

        save_ref.assert_called_once()
        self.assertEqual(metadata["strategy"], "summary_reference")
        self.assertEqual(payload["summary"]["open"], 9)
        self.assertEqual(len(payload["summary"]["top_open_items"]), 5)
        self.assertEqual(payload["ref_id"], "ctx_test")

    def test_requested_count_controls_todo_summary_size(self) -> None:
        result = {
            "ok": True,
            "action": "list_todos",
            "todos": [_todo(i) for i in range(9)],
        }
        original = json.dumps(result)

        with patch(
            "app.context.context_manager.save_context_ref", return_value="ctx_test"
        ):
            compacted, metadata = compact_tool_output(
                "list_todos",
                original,
                requested_count=6,
            )
        payload = json.loads(compacted)

        self.assertEqual(metadata["strategy"], "summary_reference")
        self.assertEqual(len(payload["summary"]["top_open_items"]), 6)
        sixth = payload["summary"]["top_open_items"][5]
        self.assertEqual(
            {key: sixth[key] for key in ("id", "title", "priority", "due_date")},
            {
                "id": 5,
                "title": "Task 5",
                "priority": "medium",
                "due_date": None,
            },
        )

    @patch("app.context.context_manager.save_context_ref", return_value="ctx_test")
    def test_large_list_uses_reference(self, save_ref) -> None:
        result = {
            "ok": True,
            "action": "list_todos",
            "todos": [_todo(i) for i in range(30)],
        }
        original = json.dumps(result)

        compacted, metadata = compact_tool_output("list_todos", original)
        payload = json.loads(compacted)

        save_ref.assert_called_once()
        self.assertEqual(metadata["strategy"], "reference")
        self.assertEqual(payload["ref_id"], "ctx_test")
        self.assertIn("read_context_ref", payload["hint"])

    @patch("app.context.context_manager.save_context_ref")
    def test_errors_and_ref_reads_are_never_compacted(self, save_ref) -> None:
        error = json.dumps({"ok": False, "error": {"code": "missing"}})
        ref_result = json.dumps(
            {"ok": True, "items": [_todo(i) for i in range(40)]}
        )

        self.assertEqual(compact_tool_output("list_todos", error)[0], error)
        self.assertEqual(compact_tool_output("read_context_ref", ref_result)[0], ref_result)
        save_ref.assert_not_called()

    def test_context_summary_reports_observation_strategy(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": json.dumps({"compaction_strategy": "summary"}),
            },
        ]

        summary = summarize_context_messages(messages)

        self.assertEqual(summary["message_count"], 2)
        self.assertEqual(summary["tool_output_count"], 1)
        self.assertEqual(
            summary["tool_outputs"][0]["compaction_strategy"], "summary"
        )


if __name__ == "__main__":
    unittest.main()
