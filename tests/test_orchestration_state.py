from __future__ import annotations

import unittest

from app.orchestration.state import GraphRoute, GraphState, append_graph_path
from app.runtime.models import RuntimeRequest


class OrchestrationStateTest(unittest.TestCase):
    def test_graph_route_values_are_stable(self) -> None:
        self.assertEqual(GraphRoute.ALLOW, "allow")
        self.assertEqual(GraphRoute.REQUIRES_CONFIRMATION, "requires_confirmation")
        self.assertEqual(GraphRoute.DENY, "deny")

    def test_append_graph_path_returns_new_path_without_mutating_input(self) -> None:
        original_path = ["classify_intent"]

        updated_path = append_graph_path(original_path, "decide_policy")

        self.assertEqual(original_path, ["classify_intent"])
        self.assertEqual(updated_path, ["classify_intent", "decide_policy"])

    def test_append_graph_path_rejects_blank_step_name(self) -> None:
        with self.assertRaises(ValueError):
            append_graph_path([], " ")

    def test_graph_state_keeps_request_local_runtime_values(self) -> None:
        request = RuntimeRequest(user_input="查看任务", session_id="session_test")

        state: GraphState = {
            "request": request,
            "intent": None,
            "policy": None,
            "route": None,
            "result": None,
            "error_code": None,
            "error_stage": None,
            "graph_path": [],
            "trace_summary": [],
        }

        self.assertIs(state["request"], request)
        self.assertEqual(state["graph_path"], [])


if __name__ == "__main__":
    unittest.main()
