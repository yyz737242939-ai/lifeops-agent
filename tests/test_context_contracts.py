from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from app.context.errors import (
    ContextContractError,
    ContextErrorCode,
    ContextProviderError,
    ConversationRepositoryError,
)
from app.context.ports import (
    ContextSummarizer,
    ConversationRepository,
    MemoryRetriever,
    ProfileProvider,
)


class ContextContractsTest(unittest.TestCase):
    def test_port_method_shapes_are_narrow_and_frozen(self) -> None:
        expected = {
            ConversationRepository.append_turn: ("self", "turn"),
            ConversationRepository.load_turns: (
                "self",
                "session_id",
                "before_or_at_sequence",
                "limit",
            ),
            ConversationRepository.append_summary: ("self", "summary"),
            ConversationRepository.load_latest_valid_summary: (
                "self",
                "session_id",
            ),
            ContextSummarizer.summarize: (
                "self",
                "previous_summary",
                "contiguous_turns",
                "budget",
                "llm_log",
            ),
            ProfileProvider.load_profile: ("self",),
            MemoryRetriever.search: (
                "self",
                "query",
                "max_items",
                "max_tokens",
            ),
        }
        for method, parameters in expected.items():
            with self.subTest(method=method.__qualname__):
                self.assertEqual(tuple(inspect.signature(method).parameters), parameters)

    def test_error_codes_are_stable_and_content_free(self) -> None:
        expected_values = (
            "context_input_too_large",
            "context_session_invalid",
            "context_path_invalid",
            "conversation_turn_append_failed",
            "conversation_history_read_failed",
            "conversation_corrupt_tail",
            "conversation_sequence_invalid",
            "context_summary_provider_failed",
            "context_summary_invalid",
            "context_summary_too_large",
            "context_profile_provider_failed",
            "context_memory_provider_failed",
            "context_assembly_failed",
            "conversation_persist_failed",
        )
        self.assertEqual(tuple(item.value for item in ContextErrorCode), expected_values)

        for error_type in (
            ContextContractError,
            ConversationRepositoryError,
            ContextProviderError,
        ):
            with self.subTest(error_type=error_type.__name__):
                error = error_type(
                    "Safe Context failure.",
                    code=ContextErrorCode.ASSEMBLY_FAILED,
                )
                self.assertEqual(error.code, "context_assembly_failed")
                self.assertEqual(str(error), "Safe Context failure.")

    def test_context_core_has_no_runtime_framework_domain_or_storage_dependency(self) -> None:
        forbidden = (
            "app.domains",
            "app.executor",
            "app.integrations",
            "app.memory",
            "app.orchestration",
            "app.planning",
            "app.policy",
            "app.runtime",
            "app.skills",
            "app.storage",
            "app.tools",
            "langgraph",
        )
        violations: list[str] = []
        for path in sorted(Path("app/context").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported = (node.module,)
                for name in imported:
                    if name.startswith(forbidden):
                        violations.append(f"{path}:{name}")

        self.assertEqual(violations, [])

        core_only_forbidden = ("app.observability", "openai")
        core_violations: list[str] = []
        for filename in ("budget.py", "errors.py", "models.py", "repository.py"):
            path = Path("app/context") / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported = (node.module,)
                for name in imported:
                    if name.startswith(core_only_forbidden):
                        core_violations.append(f"{path}:{name}")
        self.assertEqual(core_violations, [])


if __name__ == "__main__":
    unittest.main()
