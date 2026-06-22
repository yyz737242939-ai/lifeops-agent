import unittest

from app.runtime.run_state import (
    ActionRecord,
    ActionStatus,
    LoopLimits,
    RunState,
    RunStatus,
    StopReason,
)


class LoopLimitsTests(unittest.TestCase):
    def test_limits_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            LoopLimits(max_llm_rounds=0)


class RunStateTests(unittest.TestCase):
    def test_tracks_budgets_actions_and_completion(self) -> None:
        limits = LoopLimits(
            max_llm_rounds=2,
            max_tool_calls_per_round=1,
            max_total_tool_calls=2,
        )
        state = RunState(run_id="run-test")

        self.assertEqual(state.start_llm_round(limits), 1)
        state.start_tool_call(limits, calls_started_this_round=0)
        state.add_action(
            ActionRecord(
                call_id="call-1",
                tool_name="get_current_time",
                arguments={},
                status=ActionStatus.COMPLETED,
                result={"ok": True},
            )
        )
        state.complete()

        self.assertEqual(state.status, RunStatus.COMPLETED)
        self.assertEqual(state.stop_reason, StopReason.COMPLETED)
        self.assertEqual(state.llm_rounds, 1)
        self.assertEqual(state.total_tool_calls, 1)
        self.assertEqual(len(state.completed_actions), 1)
        self.assertEqual(state.to_dict()["actions"][0]["status"], "completed")

    def test_enforces_per_round_and_total_tool_budgets(self) -> None:
        limits = LoopLimits(
            max_llm_rounds=2,
            max_tool_calls_per_round=1,
            max_total_tool_calls=1,
        )
        state = RunState()

        state.start_tool_call(limits, calls_started_this_round=0)

        self.assertFalse(
            state.can_start_tool_call(limits, calls_started_this_round=1)
        )
        with self.assertRaises(RuntimeError):
            state.start_tool_call(limits, calls_started_this_round=1)

    def test_partial_stop_is_terminal(self) -> None:
        state = RunState()
        state.add_action(
            ActionRecord(
                call_id="call-1",
                tool_name="get_current_time",
                arguments={},
                status=ActionStatus.COMPLETED,
            )
        )

        state.stop(StopReason.TOOL_BUDGET_EXHAUSTED, partial=True)

        self.assertEqual(state.status, RunStatus.PARTIAL)
        self.assertEqual(state.stop_reason, StopReason.TOOL_BUDGET_EXHAUSTED)
        self.assertFalse(state.can_start_llm_round(LoopLimits()))
        self.assertFalse(
            state.can_start_tool_call(LoopLimits(), calls_started_this_round=0)
        )
        with self.assertRaises(RuntimeError):
            state.add_action(
                ActionRecord(
                    call_id="call-2",
                    tool_name="get_current_time",
                    arguments={},
                    status=ActionStatus.SKIPPED,
                )
            )


if __name__ == "__main__":
    unittest.main()
