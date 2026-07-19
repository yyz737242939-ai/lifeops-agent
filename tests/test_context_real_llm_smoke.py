from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.context.assembler import ContextAssembler
from app.context.models import (
    ContextBudget,
    ContextSummaryOutput,
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.repository import JsonlConversationRepository
from app.context.summarizer import OpenAIContextSummarizer
from app.context.summary_service import RollingSummaryService
from app.executor.model_adapter import OpenAIExecutorModelClient
from app.executor.service import ReactExecutor
from app.intent.models import IntentType
from app.planning.controller import PlanController
from app.planning.finalizer import FakePlanFinalizerClient
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerOutput,
    PlanRoute,
    PlanStepDraft,
    PlanningLimits,
)
from app.planning.planner import FakePlannerModelClient, OpenAIPlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.planning.router import FakePlanningRouteClient, OpenAIPlanningRouteClient
from app.planning.service import PlanningService
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.runtime.service import RuntimeService
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection
from tests.test_context_compiled_e2e import (
    _Intent,
    _Policy,
    _RecordingAssembler,
    _Summarizer,
)


@unittest.skipUnless(
    os.environ.get("LIFEOPS_RUN_CONTEXT_REAL_LLM_SMOKE") == "1",
    "Set LIFEOPS_RUN_CONTEXT_REAL_LLM_SMOKE=1 to call the configured LLM.",
)
class ContextRealLlmSmokeTest(unittest.TestCase):
    def test_recent_turn_direct(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = "RECENT-ORBIT-7319"
            model = _CapturingExecutorModel()
            service, _, _ = _direct_service(Path(tmpdir), model)

            first = service.handle(_request(f"Remember this exact marker: {marker}. Reply ACK.", 1))
            second = service.handle(_request("What exact marker did I just ask you to remember?", 2))

            _assert_ok(self, first, "recent direct first turn")
            _assert_ok(self, second, "recent direct second turn")
            self.assertIn(marker, second.message)
            self.assertTrue(
                any(marker in item.content for item in model.inputs[-1].context_contributions)
            )

    def test_compacted_direct_with_real_summarizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            marker = "SUMMARY-COMET-4826"
            recent_marker = "RECENT-LANTERN-2085"
            repository = JsonlConversationRepository(root)
            _append_pair(repository, 1, f"My durable marker is {marker}.", "Acknowledged.")
            _append_pair(repository, 3, "Keep the durable marker for later.", "I will keep it in context.")
            _append_pair(
                repository,
                5,
                f"My recent marker is {recent_marker}.",
                "Recent marker acknowledged.",
            )
            model = _CapturingExecutorModel()
            assembler = _RecordingAssembler(
                ContextAssembler(
                    repository,
                    RollingSummaryService(repository, OpenAIContextSummarizer()),
                )
            )
            service = _service(
                repository,
                assembler,
                model,
                budget=_budget(max_recent_turns=2),
                log_root=root / "logs",
            )

            result = service.handle(
                _request(
                    "Return the exact durable marker and the exact recent marker from our conversation.",
                    7,
                )
            )
            service.close()
            llm_rows = [
                json.loads(line)
                for path in (root / "logs").rglob("llm.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

            _assert_ok(self, result, "compacted direct")
            report = assembler.assemblies[-1].report
            self.assertIsNotNone(
                report.summary_version,
                msg=(
                    f"summary degradations={report.degradations} "
                    f"summary_llm_rows={llm_rows[:1]}"
                ),
            )
            self.assertEqual(report.selected_turn_count, 2)
            self.assertIn(marker, result.message)
            self.assertIn(recent_marker, result.message)
            projected_contents = [
                item.content for item in model.inputs[-1].context_contributions
            ]
            self.assertTrue(any(marker in item for item in projected_contents))
            self.assertTrue(any(recent_marker in item for item in projected_contents))

    def test_restart_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            marker = "RESTART-NOVA-6142"
            first_service, _, _ = _direct_service(root, _CapturingExecutorModel())
            first = first_service.handle(
                _request(f"Persist this exact marker for this session: {marker}. Reply ACK.", 1)
            )
            _assert_ok(self, first, "restart first process")

            second_service, _, _ = _direct_service(root, _CapturingExecutorModel())
            second = second_service.handle(
                _request("After restart, what exact marker belongs to this session?", 2)
            )

            _assert_ok(self, second, "restart second process")
            self.assertIn(marker, second.message)

    def test_planner_preview_uses_conversation_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            marker = "PLANNER-SEQUENCE-9054"
            repository = JsonlConversationRepository(root)
            _append_pair(
                repository,
                1,
                f"For the next plan, preserve this constraint: {marker}.",
                "Constraint acknowledged.",
            )
            planner = _CapturingPlannerModel()
            route = _CapturingRouteModel()
            conn = create_test_connection()
            try:
                service = _planning_service(
                    repository,
                    planner,
                    route,
                    conn,
                    executor_model=_CapturingExecutorModel(),
                )
                result = service.handle(
                    RuntimeRequest(
                        "Create a two-step no-tool plan: first restate my prior constraint, then summarize it.",
                        "session_context_real",
                        turn_id="turn_plan",
                        run_id="run_plan",
                    )
                )

                self.assertEqual(
                    result.status,
                    RuntimeStatus.REQUIRES_CONFIRMATION,
                    msg=f"planner preview status={result.status.value} error={result.error_code}",
                )
                self.assertEqual(result.tool_result["type"], "plan_preview")
                self.assertTrue(
                    any(marker in item.content for item in route.inputs[0].context_contributions)
                )
                self.assertTrue(
                    any(marker in item.content for item in planner.inputs[0].context_contributions)
                )
            finally:
                conn.close()

    def test_shared_planstep_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            marker = "PLANSTEP-AURORA-3371"
            repository = JsonlConversationRepository(root)
            _append_pair(
                repository,
                1,
                f"Shared plan context marker: {marker}.",
                "Marker acknowledged.",
            )
            model = _CapturingExecutorModel()
            conn = create_test_connection()
            try:
                service, assembler, summarizer = _deterministic_plan_service(
                    repository, conn, model
                )
                goal = "Complete the two no-tool reasoning steps from the preview."
                preview = service.handle(
                    RuntimeRequest(
                        goal,
                        "session_context_real",
                        turn_id="turn_preview",
                        run_id="run_preview",
                    )
                )
                self.assertEqual(preview.status, RuntimeStatus.REQUIRES_CONFIRMATION)
                summarizer.calls.clear()
                command = PlanCommand(
                    "confirm_real_context",
                    preview.tool_result["plan_id"],
                    "session_context_real",
                    preview.tool_result["revision"],
                    PlanCommandAction.CONFIRM,
                )
                result = service.handle_plan_command(
                    command,
                    RuntimeRequest(
                        goal,
                        "session_context_real",
                        turn_id="turn_confirm",
                        run_id="run_confirm",
                    ),
                )

                _assert_ok(self, result, "shared PlanStep assembly")
                self.assertEqual(len(model.inputs), 2)
                self.assertEqual(len(summarizer.calls), 1)
                assembly_id = assembler.assemblies[-1].assembly_id
                for model_input in model.inputs:
                    self.assertTrue(
                        any(marker in item.content for item in model_input.context_contributions)
                    )
                    self.assertTrue(
                        all(
                            f"context-assembly://{assembly_id}/" in item.source
                            for item in model_input.context_contributions
                        )
                    )
            finally:
                conn.close()


class _CapturingExecutorModel:
    def __init__(self) -> None:
        self._delegate = OpenAIExecutorModelClient()
        self.inputs = []

    def decide(self, model_input, *, llm_log=None):
        self.inputs.append(model_input)
        return self._delegate.decide(model_input, llm_log=llm_log)


class _CapturingPlannerModel:
    def __init__(self) -> None:
        self._delegate = OpenAIPlannerModelClient()
        self.inputs = []

    def create_plan(self, planner_input, *, llm_log=None):
        self.inputs.append(planner_input)
        return self._delegate.create_plan(planner_input, llm_log=llm_log)

    def replan(self, replan_input, *, llm_log=None):
        return self._delegate.replan(replan_input, llm_log=llm_log)


class _CapturingRouteModel:
    def __init__(self) -> None:
        self._delegate = OpenAIPlanningRouteClient()
        self.inputs = []

    def decide(self, route_input, *, llm_log=None):
        self.inputs.append(route_input)
        return self._delegate.decide(route_input, llm_log=llm_log)


class _NoSkillClient:
    def select(self, request, skill_metadata, *, llm_log=None):
        return {"selected_skill_ids": [], "reason": "context smoke"}


def _skill_service() -> SkillService:
    return SkillService(SkillRegistry(), _NoSkillClient())


class _PreservingSummarizer:
    def __init__(self) -> None:
        self.calls = []

    def summarize(self, previous_summary, contiguous_turns, budget, *, llm_log=None):
        self.calls.append((previous_summary, contiguous_turns, budget))
        parts = []
        if previous_summary is not None:
            parts.append(previous_summary.content)
        parts.extend(turn.content for turn in contiguous_turns)
        return ContextSummaryOutput(" ".join(parts), "fixture", "preserving")


def _direct_service(root: Path, model):
    repository = JsonlConversationRepository(root)
    assembler = _RecordingAssembler(
        ContextAssembler(
            repository,
            RollingSummaryService(repository, _Summarizer()),
        )
    )
    return _service(repository, assembler, model), repository, assembler


def _service(
    repository,
    assembler,
    model,
    *,
    budget: ContextBudget | None = None,
    log_root: Path | None = None,
):
    return RuntimeService(
        _skill_service(),
        intent_service=_Intent(IntentType.CHAT),
        policy_service=_Policy(),
        execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
        executor=ReactExecutor(model),
        conversation_repository=repository,
        context_assembler=assembler,
        context_budget=budget or _budget(),
        log_root=log_root,
    )


def _planning_service(repository, planner, route, conn, *, executor_model):
    limits = PlanningLimits(max_plan_steps=4)
    plan_repository = SqlitePlanRepository(conn)
    planning = PlanningService(planner, plan_repository, limits=limits)
    executor = ReactExecutor(executor_model)
    assembler = _RecordingAssembler(
        ContextAssembler(repository, RollingSummaryService(repository, _Summarizer()))
    )
    return RuntimeService(
        _skill_service(),
        intent_service=_Intent(IntentType.PLAN_REQUEST),
        policy_service=_Policy(),
        execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
        executor=executor,
        planning_route_client=route,
        planning_service=planning,
        plan_controller=PlanController(plan_repository, executor, limits=limits, planner=planner),
        planning_limits=limits,
        conversation_repository=repository,
        context_assembler=assembler,
        context_budget=_budget(),
    )


def _deterministic_plan_service(repository, conn, model):
    limits = PlanningLimits(max_plan_steps=3)
    draft = PlanDraft(
        (
            PlanStepDraft(
                "recall",
                1,
                "Read the supplied conversation context and state its exact marker.",
                "The marker is stated exactly.",
            ),
            PlanStepDraft(
                "finish",
                2,
                "State that the context-aware two-step plan is complete.",
                "Completion is stated.",
                ("recall",),
            ),
        )
    )
    planner = FakePlannerModelClient(draft)
    plan_repository = SqlitePlanRepository(conn)
    planning = PlanningService(planner, plan_repository, limits=limits)
    executor = ReactExecutor(model)
    summarizer = _PreservingSummarizer()
    assembler = _RecordingAssembler(
        ContextAssembler(repository, RollingSummaryService(repository, summarizer))
    )
    service = RuntimeService(
        _skill_service(),
        intent_service=_Intent(IntentType.PLAN_REQUEST),
        policy_service=_Policy(),
        execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
        executor=executor,
        planning_route_client=FakePlanningRouteClient(PlanRoute("fixture multi-step")),
        planning_service=planning,
        plan_controller=PlanController(
            plan_repository,
            executor,
            limits=limits,
            planner=planner,
            finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("plan complete")),
        ),
        planning_limits=limits,
        conversation_repository=repository,
        context_assembler=assembler,
        context_budget=_budget(max_recent_turns=0),
    )
    return service, assembler, summarizer


def _budget(*, max_recent_turns: int = 8) -> ContextBudget:
    return ContextBudget(
        max_total_tokens=4000,
        max_recent_turns=max_recent_turns,
        max_summary_tokens=1000,
        max_profile_tokens=0,
        max_memory_items=0,
        max_memory_tokens=0,
        max_current_input_tokens=2000,
    )


def _request(text: str, number: int) -> RuntimeRequest:
    return RuntimeRequest(
        text,
        "session_context_real",
        turn_id=f"turn_{number}",
        run_id=f"run_{number}",
    )


def _append_pair(repository, start_sequence: int, user_content: str, assistant_content: str):
    repository.append_turn(
        ConversationTurn(
            1,
            "session_context_real",
            f"history_{start_sequence}",
            start_sequence,
            ConversationRole.USER,
            ConversationTurnKind.NATURAL_INPUT,
            user_content,
            f"history_run_{start_sequence}",
            "2026-07-16T00:00:00Z",
        )
    )
    repository.append_turn(
        ConversationTurn(
            1,
            "session_context_real",
            f"history_{start_sequence + 1}",
            start_sequence + 1,
            ConversationRole.ASSISTANT,
            ConversationTurnKind.FINAL_ANSWER,
            assistant_content,
            f"history_run_{start_sequence}",
            "2026-07-16T00:00:01Z",
        )
    )


def _assert_ok(test: unittest.TestCase, result, label: str) -> None:
    test.assertEqual(
        result.status,
        RuntimeStatus.OK,
        msg=f"{label}: status={result.status.value} error_code={result.error_code}",
    )


if __name__ == "__main__":
    unittest.main()
