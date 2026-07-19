import unittest
from types import SimpleNamespace

from app.planning.executor_agent import ExecutorAgent, StepExecutionContext
from app.runtime.run_state import RunState


class FakeAgent:
    def __init__(self) -> None:
        self.received_run_state = None
        self.received_turn = None

    def _run_agent_loop(self, run_state: RunState, turn) -> str:
        self.received_run_state = run_state
        self.received_turn = turn
        return "step executed"


class ExecutorAgentTests(unittest.TestCase):
    def test_execute_step_wraps_existing_agent_loop(self) -> None:
        fake_agent = FakeAgent()
        executor = ExecutorAgent(fake_agent)
        run_state = RunState()
        turn = SimpleNamespace(user_input="Execute the current step.")

        result = executor.execute_step(
            StepExecutionContext(
                run_state=run_state,
                turn=turn,
                plan_id="plan-1",
                plan_step_id="step-1",
            )
        )

        self.assertEqual(result.answer, "step executed")
        self.assertIs(result.run_state, run_state)
        self.assertEqual(result.plan_id, "plan-1")
        self.assertEqual(result.plan_step_id, "step-1")
        self.assertIs(fake_agent.received_run_state, run_state)
        self.assertIs(fake_agent.received_turn, turn)


if __name__ == "__main__":
    unittest.main()
