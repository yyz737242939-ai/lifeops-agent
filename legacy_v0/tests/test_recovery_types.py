import unittest

from pydantic import ValidationError

from app.runtime.recovery_types import (
    PersistentActionRecord,
    RunRecord,
)


class PersistentActionRecordTests(unittest.TestCase):
    def test_create_and_serialize_action_record(self) -> None:
        action = PersistentActionRecord(
            run_id="run-test",
            call_id="call-1",
            tool_name="list_tasks",
            arguments_hash="hash-1",
            arguments_preview={"limit": 3},
            status="completed",
            effect="read",
            result_summary="Listed active tasks.",
        )

        serialized = action.to_dict()
        restored = PersistentActionRecord.from_dict(serialized)

        self.assertTrue(action.action_id.startswith("action_"))
        self.assertEqual(serialized["status"], "completed")
        self.assertEqual(serialized["effect"], "read")
        self.assertEqual(restored, action)

    def test_action_supports_failed_and_skipped_statuses(self) -> None:
        failed = PersistentActionRecord(
            run_id="run-test",
            call_id="call-1",
            tool_name="create_task",
            arguments_hash="hash-1",
            status="failed",
            effect="write",
            error_summary="Tool returned an error.",
        )
        skipped = PersistentActionRecord(
            run_id="run-test",
            call_id="call-2",
            tool_name="create_task",
            arguments_hash="hash-2",
            status="skipped",
            effect="write",
        )

        self.assertEqual(failed.status, "failed")
        self.assertEqual(skipped.status, "skipped")

    def test_rejects_invalid_action_status(self) -> None:
        with self.assertRaises(ValidationError):
            PersistentActionRecord(
                run_id="run-test",
                call_id="call-1",
                tool_name="list_tasks",
                arguments_hash="hash-1",
                status="running",
                effect="read",
            )


class RunRecordTests(unittest.TestCase):
    def test_create_serialize_and_restore_run_record(self) -> None:
        action = PersistentActionRecord(
            run_id="run-test",
            call_id="call-1",
            tool_name="add_task_note",
            arguments_hash="hash-1",
            arguments_preview={"task_id": "task-1"},
            status="completed",
            effect="write",
            idempotency_key="idem-1",
            result_summary="Note added.",
        )
        run = RunRecord(
            run_id="run-test",
            status="partial",
            stop_reason="llm_request_failed",
            task_id="task-1",
            user_input_summary="Continue the active task.",
            last_successful_action=action,
            action_count=1,
            actions=[action],
        )

        serialized = run.to_dict()
        restored = RunRecord.from_dict(serialized)

        self.assertEqual(serialized["status"], "partial")
        self.assertEqual(serialized["last_successful_action"]["status"], "completed")
        self.assertEqual(serialized["actions"][0]["effect"], "write")
        self.assertEqual(restored, run)

    def test_run_supports_all_recovery_statuses(self) -> None:
        statuses = [
            "running",
            "completed",
            "partial",
            "failed",
            "stopped",
            "interrupted",
        ]

        records = [
            RunRecord(
                run_id=f"run-{status}",
                status=status,
                user_input_summary=f"{status} run",
            )
            for status in statuses
        ]

        self.assertEqual([record.status for record in records], statuses)

    def test_rejects_invalid_run_status_and_negative_action_count(self) -> None:
        with self.assertRaises(ValidationError):
            RunRecord(
                run_id="run-test",
                status="paused",
                user_input_summary="Invalid status.",
            )

        with self.assertRaises(ValueError):
            RunRecord(
                run_id="run-test",
                status="running",
                user_input_summary="Invalid action count.",
                action_count=-1,
            )


if __name__ == "__main__":
    unittest.main()
