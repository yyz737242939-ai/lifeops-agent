from __future__ import annotations

import ast
import sqlite3
import unittest
from pathlib import Path

from app.runtime.bootstrap import _build_tool_runtime


EXPECTED_RESEARCH_TOOLS = (
    "research.append_revision",
    "research.build_brief",
    "research.create_note",
    "research.create_topic",
    "research.link_items",
    "research.save_brief",
    "research.save_source",
    "research.search_knowledge",
    "research.search_papers",
)


class ResearchMcpSurfaceTest(unittest.TestCase):
    def test_runtime_exposes_exactly_nine_research_tools(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            runtime = _build_tool_runtime(conn, Path("app/skills"))
            names = tuple(
                definition.name
                for definition in runtime.registry.list_definitions()
                if definition.name.startswith("research.")
            )
        finally:
            conn.close()

        self.assertEqual(names, EXPECTED_RESEARCH_TOOLS)

    def test_research_implementation_does_not_import_planner_or_executor(self) -> None:
        roots = (
            Path("app/domains/research"),
            Path("app/integrations/mcp"),
            Path("app/integrations/research_mcp"),
        )
        violations: list[str] = []
        for root in roots:
            for path in root.glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    module = None
                    if isinstance(node, ast.ImportFrom):
                        module = node.module
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(("app.planning", "app.executor")):
                                violations.append(f"{path}:{alias.name}")
                    if module and module.startswith(("app.planning", "app.executor")):
                        violations.append(f"{path}:{module}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
