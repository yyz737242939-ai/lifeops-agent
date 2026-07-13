from __future__ import annotations

import ast
import unittest
from pathlib import Path


class Stage5ArchitectureContractTest(unittest.TestCase):
    def test_domains_do_not_import_runtime_or_agent_framework_layers(self) -> None:
        forbidden = (
            "app.orchestration",
            "app.runtime",
            "app.skills",
            "langgraph",
        )
        violations: list[str] = []
        for path in sorted(Path("app/domains").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = [node.module]
                for name in names:
                    if name.startswith(forbidden):
                        violations.append(f"{path}:{name}")

        self.assertEqual(violations, [])

    def test_production_bootstrap_does_not_depend_on_test_assets(self) -> None:
        source = Path("app/runtime/bootstrap.py").read_text(encoding="utf-8")

        self.assertNotIn("tests/fixtures", source)
        self.assertNotIn("FixtureCalendarAvailabilityAdapter", source)
        self.assertNotIn("FixtureResearchSourcePort", source)


if __name__ == "__main__":
    unittest.main()
