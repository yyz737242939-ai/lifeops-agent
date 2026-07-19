from __future__ import annotations

import ast
import unittest
from dataclasses import fields
from pathlib import Path

from app.executor.models import (
    ExecutionLimits,
    FinalAnswerActionClaim,
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    PlanStepDependencyResult,
    PlanStepExecutionInput,
    ToolActionDecision,
    ToolObservation,
)
from app.executor.state import ExecutorState


class ExecutorContractTest(unittest.TestCase):
    def test_public_model_fields_are_frozen(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(ExecutionLimits)),
            ("max_steps",),
        )
        self.assertEqual(
            tuple(item.name for item in fields(ToolActionDecision)),
            ("call",),
        )
        self.assertEqual(
            tuple(item.name for item in fields(FinalAnswerDecision)),
            ("message", "action_claims"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(FinalAnswerActionClaim)),
            ("claim_id", "call_id", "evidence_refs"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(GoalNotAchievedDecision)),
            ("reason_code",),
        )
        self.assertEqual(
            tuple(item.name for item in fields(PlanStepDependencyResult)),
            ("step_id", "safe_result_summary", "observations"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(PlanStepExecutionInput)),
            (
                "plan_id",
                "revision",
                "step_id",
                "plan_goal",
                "current_objective",
                "expected_outcome",
                "dependency_results",
                "max_steps",
            ),
        )
        self.assertEqual(
            tuple(item.name for item in fields(ToolObservation)),
            (
                "step_index",
                "call_id",
                "tool_name",
                "status",
                "output",
                "error",
                "evidence",
            ),
        )
        self.assertEqual(
            tuple(item.name for item in fields(ExecutorResult)),
            (
                "run_id",
                "status",
                "stop_reason",
                "final_message",
                "step_count",
                "observations",
                "last_tool_result",
                "error_code",
                "final_answer_claims",
            ),
        )

    def test_status_and_stop_reason_values_are_frozen(self) -> None:
        self.assertEqual(
            {item.value for item in ExecutorStatus},
            {"completed", "stopped", "failed"},
        )
        self.assertEqual(
            {item.value for item in ExecutorStopReason},
            {
                "final_answer",
                "confirmation_required",
                "limit_reached",
                "goal_not_achieved",
                "safety_denied",
                "model_failed",
                "invalid_model_action",
                "input_provider_failed",
                "executor_internal_failed",
            },
        )

    def test_models_and_state_have_no_private_reasoning_or_sensitive_fields(self) -> None:
        exposed_names = {
            item.name
            for model in (
                ExecutionLimits,
                ToolActionDecision,
                FinalAnswerDecision,
                GoalNotAchievedDecision,
                PlanStepDependencyResult,
                PlanStepExecutionInput,
                ToolObservation,
                ExecutorResult,
            )
            for item in fields(model)
        } | set(ExecutorState.__annotations__)

        self.assertTrue(
            exposed_names.isdisjoint(
                {
                    "thought",
                    "reasoning",
                    "chain_of_thought",
                    "graph_state",
                    "policy",
                    "intent",
                    "exception",
                    "exception_text",
                    "domain_object",
                    "provider_response",
                    "arguments",
                }
            )
        )

    def test_executor_state_is_minimal_and_request_local(self) -> None:
        self.assertEqual(
            tuple(ExecutorState.__annotations__),
            (
                "request",
                "prompt_contributions",
                "tool_catalog",
                "observations",
                "current_decision",
                "step_count",
                "result",
                "error_code",
                "executor_path",
            ),
        )

    def test_executor_has_no_domain_storage_repository_or_provider_sdk_dependency(self) -> None:
        forbidden = (
            "app.domains.research",
            "app.domains.travel",
            "app.storage",
            "langchain",
        )
        violations: list[str] = []
        for path in sorted(Path("app/executor").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = [node.module]
                for name in names:
                    if name.startswith(forbidden) or "repository" in name:
                        violations.append(f"{path}:{name}")

        self.assertEqual(violations, [])

    def test_executor_core_does_not_depend_on_provider_sdk(self) -> None:
        violations: list[str] = []
        for filename in (
            "models.py",
            "state.py",
            "ports.py",
            "adapters.py",
            "routes.py",
            "graph.py",
            "service.py",
        ):
            path = Path("app/executor") / filename
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = [node.module]
                violations.extend(
                    f"{path}:{name}"
                    for name in names
                    if name.startswith("openai")
                )

        self.assertEqual(violations, [])

    def test_executor_models_ports_and_adapters_do_not_depend_on_langgraph(self) -> None:
        violations: list[str] = []
        for filename in ("models.py", "state.py", "ports.py", "adapters.py"):
            path = Path("app/executor") / filename
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = [node.module]
                violations.extend(
                    f"{path}:{name}"
                    for name in names
                    if name.startswith("langgraph")
                )

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
