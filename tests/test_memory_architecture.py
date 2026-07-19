from __future__ import annotations

import ast
import unittest
from pathlib import Path


_MEMORY_ROOT = Path(__file__).resolve().parents[1] / "app" / "memory"
_CORE_AND_CONTEXT_ADAPTERS = (
    "document_store.py",
    "errors.py",
    "matching.py",
    "models.py",
    "profile.py",
    "repository.py",
    "retrieval_core.py",
    "retriever.py",
    "service.py",
)
_FORBIDDEN_PREFIXES = (
    "langgraph",
    "openai",
    "app.domains",
    "app.executor",
    "app.orchestration",
    "app.planning",
    "app.tools",
)


class MemoryArchitectureContractTest(unittest.TestCase):
    def test_core_and_context_adapters_do_not_depend_on_runtime_framework_or_tools(self) -> None:
        violations = []
        for filename in _CORE_AND_CONTEXT_ADAPTERS:
            path = _MEMORY_ROOT / filename
            for imported in _imports(path):
                if imported.startswith(_FORBIDDEN_PREFIXES):
                    violations.append(f"{filename}: {imported}")

        self.assertEqual(violations, [])

    def test_tool_and_observability_dependencies_are_isolated_to_tools_adapter(self) -> None:
        consumers = {}
        for path in sorted(_MEMORY_ROOT.glob("*.py")):
            imported = tuple(
                name
                for name in _imports(path)
                if name.startswith(("app.tools", "app.observability"))
            )
            if imported:
                consumers[path.name] = imported

        self.assertEqual(set(consumers), {"tools.py"})
        self.assertTrue(any(name.startswith("app.tools") for name in consumers["tools.py"]))
        self.assertIn("app.observability.logger", consumers["tools.py"])


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return tuple(names)


if __name__ == "__main__":
    unittest.main()
