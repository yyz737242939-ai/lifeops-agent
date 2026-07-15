from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from app.orchestration.state import GraphState
from app.planning.controller import PlanController
from app.planning.service import PlanningService


class PlanningArchitectureTest(unittest.TestCase):
    def test_planning_core_does_not_depend_on_domains_or_langgraph(self) -> None:
        root = Path("app/planning")
        forbidden = ("app.domains", "langgraph")

        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(item.name for item in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported.append(node.module)
            with self.subTest(path=path):
                self.assertFalse(
                    any(name.startswith(forbidden) for name in imported), imported
                )

    def test_services_depend_on_repository_port_not_sqlite_adapter(self) -> None:
        self.assertEqual(
            inspect.signature(PlanningService.__init__)
            .parameters["repository"]
            .annotation,
            "PlanRepository",
        )
        self.assertEqual(
            inspect.signature(PlanController.__init__)
            .parameters["repository"]
            .annotation,
            "PlanRepository",
        )

    def test_outer_graph_state_keeps_only_route_level_planning_data(self) -> None:
        self.assertEqual(
            tuple(GraphState.__annotations__),
            (
                "request",
                "intent",
                "policy",
                "route",
                "skill_selection",
                "prompt_contributions",
                "planning_route",
                "result",
                "error_code",
                "error_stage",
                "graph_path",
            ),
        )
        self.assertTrue(
            set(GraphState.__annotations__).isdisjoint(
                {"plan_run", "plan_steps", "tool_runtime", "observations"}
            )
        )


if __name__ == "__main__":
    unittest.main()
