import unittest

from app.runtime.interaction_state import (
    InteractionState,
    PendingConfirmation,
    PendingConfirmationStatus,
    RiskLevel,
)


class PendingConfirmationTests(unittest.TestCase):
    def test_requires_valid_lifecycle_fields(self) -> None:
        with self.assertRaises(ValueError):
            PendingConfirmation(
                operation="",
                risk_level=RiskLevel.HIGH,
                scope_summary="delete completed todos",
                arguments={},
                source_user_input="delete all completed todos",
            )

        with self.assertRaises(ValueError):
            PendingConfirmation(
                operation="delete_completed_todos",
                risk_level=RiskLevel.HIGH,
                scope_summary="delete completed todos",
                arguments={},
                source_user_input="delete all completed todos",
                expires_after_turns=0,
            )

    def test_confirmed_pending_can_be_consumed_once(self) -> None:
        pending = PendingConfirmation(
            operation="delete_completed_todos",
            tool_name="delete_todo",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all completed todos",
            arguments={"status": "done"},
            source_user_input="delete all completed todos",
            created_turn_index=3,
        )

        pending.confirm()
        pending.consume(turn_index=4)

        self.assertEqual(pending.status, PendingConfirmationStatus.CONSUMED)
        self.assertEqual(pending.consumed_turn_index, 4)
        with self.assertRaises(RuntimeError):
            pending.consume(turn_index=4)

    def test_terminal_pending_cannot_be_confirmed_again(self) -> None:
        pending = PendingConfirmation(
            operation="delete_memory",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all active memories",
            arguments={"scope": "all"},
            source_user_input="delete all memories",
        )

        pending.cancel()

        with self.assertRaises(RuntimeError):
            pending.confirm()


class InteractionStateTests(unittest.TestCase):
    def test_create_pending_uses_current_turn_and_serializes_scope(self) -> None:
        state = InteractionState(turn_index=2)

        pending = state.create_pending_confirmation(
            operation="delete_completed_todos",
            tool_name="delete_todo",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all completed todos",
            arguments={"status": "done"},
            source_user_input="delete all completed todos",
        )

        self.assertEqual(pending.created_turn_index, 2)
        self.assertIs(state.active_pending_confirmation, pending)
        serialized = state.to_dict()
        self.assertEqual(serialized["state_scope"], "cross_turn_interaction_safety")
        self.assertEqual(
            serialized["pending_confirmation"]["status"],
            "pending",
        )

    def test_new_pending_supersedes_existing_active_pending(self) -> None:
        state = InteractionState()
        first = state.create_pending_confirmation(
            operation="delete_completed_todos",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all completed todos",
            arguments={"status": "done"},
            source_user_input="delete all completed todos",
        )

        second = state.create_pending_confirmation(
            operation="delete_today_completed_todos",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete today completed todos",
            arguments={"status": "done", "completed_on": "today"},
            source_user_input="only delete today completed todos",
        )

        self.assertEqual(first.status, PendingConfirmationStatus.SUPERSEDED)
        self.assertIs(state.active_pending_confirmation, second)

    def test_cancel_pending_leaves_no_active_pending(self) -> None:
        state = InteractionState()
        state.create_pending_confirmation(
            operation="delete_memory",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all active memories",
            arguments={"scope": "all"},
            source_user_input="delete all memories",
        )

        cancelled = state.cancel_pending()

        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, PendingConfirmationStatus.CANCELLED)
        self.assertIsNone(state.active_pending_confirmation)

    def test_pending_expires_after_configured_turn_window(self) -> None:
        state = InteractionState()
        pending = state.create_pending_confirmation(
            operation="delete_completed_todos",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all completed todos",
            arguments={"status": "done"},
            source_user_input="delete all completed todos",
            expires_after_turns=1,
        )

        state.advance_turn()
        self.assertEqual(pending.status, PendingConfirmationStatus.PENDING)

        state.advance_turn()

        self.assertEqual(pending.status, PendingConfirmationStatus.EXPIRED)
        self.assertIsNone(state.active_pending_confirmation)
        self.assertIsNone(state.confirm_pending())

    def test_confirm_and_consume_clears_pending_from_state(self) -> None:
        state = InteractionState(turn_index=5)
        created = state.create_pending_confirmation(
            operation="delete_completed_todos",
            risk_level=RiskLevel.HIGH,
            scope_summary="delete all completed todos",
            arguments={"status": "done"},
            source_user_input="delete all completed todos",
        )

        confirmed = state.confirm_pending()
        consumed = state.consume_confirmed_pending()

        self.assertIs(confirmed, created)
        self.assertIs(consumed, created)
        self.assertEqual(created.status, PendingConfirmationStatus.CONSUMED)
        self.assertEqual(created.consumed_turn_index, 5)
        self.assertIsNone(state.pending_confirmation)
        self.assertIsNone(state.consume_confirmed_pending())

    def test_isolated_confirmation_does_not_create_pending(self) -> None:
        state = InteractionState()

        self.assertIsNone(state.confirm_pending())
        self.assertIsNone(state.pending_confirmation)


if __name__ == "__main__":
    unittest.main()
