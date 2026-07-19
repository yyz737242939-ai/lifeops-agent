from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.context.assembler import ContextAssembler
from app.context.errors import ContextErrorCode, ConversationRepositoryError
from app.context.models import (
    ContextBudget,
    ContextContributionKind,
    ContextDegradationComponent,
    ContextSummaryOutput,
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.repository import JsonlConversationRepository
from app.context.summary_service import RollingSummaryService
from app.executor.models import FinalAnswerDecision, ToolActionDecision
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import LifeOpsSpanKind, SpanLinkType
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
from app.planning.planner import FakePlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.planning.router import FakePlanningRouteClient
from app.planning.service import PlanningService
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.runtime.service import RuntimeService
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.tools.models import (
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection, create_test_skill_service


class ContextCompiledE2ETest(unittest.TestCase):
    def test_two_round_direct_references_first_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _ContextAwareModel("first-round-value")
            service, _, _ = _direct_service(Path(tmpdir), model)

            first = service.handle(_request("first-round-value", 1))
            second = service.handle(_request("What did I say before?", 2))

            self.assertEqual(first.status, RuntimeStatus.OK)
            self.assertEqual(second.message, "remembered:first-round-value")
            self.assertIn(
                "first-round-value",
                [item.content for item in model.inputs[1].context_contributions],
            )

    def test_long_session_summarizes_and_keeps_recent_and_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summarizer = _Summarizer()
            budget = _budget(max_recent_turns=2)
            model = _RecordingModel()
            service, _, assembler = _direct_service(
                Path(tmpdir), model, summarizer=summarizer, budget=budget
            )

            service.handle(_request("turn-one", 1))
            service.handle(_request("turn-two", 2))
            service.handle(_request("turn-three-current", 3))

            assembly = assembler.assemblies[-1]
            kinds = [item.kind for item in assembly.contributions]
            self.assertEqual(len(summarizer.calls), 1)
            self.assertIn(ContextContributionKind.CONVERSATION_SUMMARY, kinds)
            self.assertLessEqual(
                kinds.count(ContextContributionKind.CONVERSATION_TURN), 2
            )
            self.assertEqual(
                assembly.contributions[-1].kind,
                ContextContributionKind.CURRENT_INPUT,
            )
            self.assertEqual(assembly.contributions[-1].content, "turn-three-current")

    def test_restart_recovers_same_session_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_service, _, _ = _direct_service(root, _RecordingModel())
            first_service.handle(_request("restart-memory", 1))

            second_model = _ContextAwareModel("restart-memory")
            second_service, _, _ = _direct_service(root, second_model)
            result = second_service.handle(_request("continue after restart", 2))

            self.assertEqual(result.message, "remembered:restart-memory")
            self.assertEqual(
                len(JsonlConversationRepository(root).load_turns("session_e2e", None, None)),
                4,
            )

    def test_planning_preview_uses_context_without_persisting_it_as_plan_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = JsonlConversationRepository(root)
            _append_visible_pair(repository, "durable-conversation-fact")
            conn = create_test_connection()
            try:
                service, planner, plan_repository, _ = _planning_service(
                    root, repository, conn, step_count=1
                )
                result = service.handle(
                    RuntimeRequest(
                        "make a plan",
                        "session_e2e",
                        turn_id="turn_plan",
                        run_id="run_plan",
                    )
                )

                self.assertEqual(result.status, RuntimeStatus.REQUIRES_CONFIRMATION)
                planner_context = planner.create_inputs[0].context_contributions
                self.assertIn(
                    "durable-conversation-fact",
                    [item.content for item in planner_context],
                )
                run, _ = plan_repository.get_plan(
                    "session_e2e", result.tool_result["plan_id"]
                )
                self.assertFalse(hasattr(run, "context_contributions"))
                self.assertNotIn("durable-conversation-fact", json.dumps(vars(run)))
            finally:
                conn.close()

    def test_confirmed_multi_step_plan_reuses_one_assembly_and_summarizes_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repository = JsonlConversationRepository(root)
            _append_visible_pair(repository, "older plan context")
            summarizer = _Summarizer()
            plan_model = _RecordingModel()
            conn = create_test_connection()
            service = None
            try:
                service, _, _, assembler = _planning_service(
                    root,
                    repository,
                    conn,
                    step_count=2,
                    summarizer=summarizer,
                    budget=_budget(max_recent_turns=0),
                    executor_model=plan_model,
                    log_root=root / "logs",
                )
                preview = service.handle(
                    RuntimeRequest(
                        "make two steps",
                        "session_e2e",
                        turn_id="turn_preview",
                        run_id="run_preview",
                    )
                )
                summarizer.calls.clear()
                command = PlanCommand(
                    "confirm_1",
                    preview.tool_result["plan_id"],
                    "session_e2e",
                    preview.tool_result["revision"],
                    PlanCommandAction.CONFIRM,
                )
                result = service.handle_plan_command(
                    command,
                    RuntimeRequest(
                        "make two steps",
                        "session_e2e",
                        turn_id="turn_confirm",
                        run_id="run_confirm",
                    ),
                )

                self.assertEqual(result.status, RuntimeStatus.OK)
                self.assertEqual(len(summarizer.calls), 1)
                self.assertEqual(len(plan_model.inputs), 2)
                assembly_id = assembler.assemblies[-1].assembly_id
                self.assertTrue(
                    all(
                        all(
                            f"context-assembly://{assembly_id}/" in item.source
                            for item in model_input.context_contributions
                        )
                        for model_input in plan_model.inputs
                    )
                )
                reader = TraceReader(FileTraceStore(root / "logs"))
                preview_graph = reader.find_by_run("run_preview")
                confirm_graph = reader.find_by_run("run_confirm")
                self.assertEqual(
                    [
                        link.target_trace_id
                        for link in confirm_graph.links
                        if link.link_type is SpanLinkType.PLAN_CONTINUATION
                    ],
                    [preview_graph.trace.trace_id],
                )
                self.assertEqual(
                    len(
                        [
                            span
                            for span in confirm_graph.spans_by_id.values()
                            if span.lifeops_span_kind is LifeOpsSpanKind.EXECUTOR
                        ]
                    ),
                    2,
                )
                preview_span = next(
                    span
                    for span in preview_graph.spans_by_id.values()
                    if span.name == "planning.route"
                )
                self.assertEqual(
                    preview_span.attributes["lifeops.plan.id"],
                    preview.tool_result["plan_id"],
                )
            finally:
                if service is not None:
                    service.close()
                conn.close()

    def test_history_read_failure_degrades_to_current_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = JsonlConversationRepository(Path(tmpdir))
            repository = _AssemblerReadFailureRepository(base)
            model = _RecordingModel()
            service, _, assembler = _direct_service(
                Path(tmpdir), model, repository=repository
            )

            result = service.handle(_request("current survives", 1))

            self.assertEqual(result.status, RuntimeStatus.OK)
            assembly = assembler.assemblies[0]
            self.assertEqual(
                [item.kind for item in assembly.contributions],
                [ContextContributionKind.CURRENT_INPUT],
            )
            self.assertEqual(assembly.contributions[0].content, "current survives")
            self.assertEqual(
                assembly.report.degradations[0].component,
                ContextDegradationComponent.CONVERSATION_HISTORY,
            )

    def test_current_user_append_failure_stops_before_llm_and_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _ToolModel()
            skill_client = _CountingSkillClient()
            repository = _UserAppendFailureRepository()
            service, _, _ = _direct_service(
                Path(tmpdir),
                model,
                repository=repository,
                skill_service=SkillService(SkillRegistry(), skill_client),
            )

            result = service.handle(_request("must stop", 1))

            self.assertEqual(result.status, RuntimeStatus.ERROR)
            self.assertEqual(result.error_code, ContextErrorCode.TURN_APPEND_FAILED.value)
            self.assertEqual(skill_client.calls, 0)
            self.assertEqual(model.calls, 0)

    def test_assistant_append_failure_does_not_fake_tool_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            counter = {"calls": 0}
            runtime = _counter_runtime(counter)
            base = JsonlConversationRepository(Path(tmpdir))
            repository = _AssistantAppendFailureRepository(base)
            model = _ToolModel()
            service, _, _ = _direct_service(
                Path(tmpdir),
                model,
                repository=repository,
                execution_scope_factory=lambda: runtime,
            )

            result = service.handle(_request("use counter", 1))

            self.assertEqual(result.status, RuntimeStatus.OK)
            self.assertEqual(counter["calls"], 1)
            self.assertEqual(model.calls, 2)
            turns = base.load_turns("session_e2e", None, None)
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0].role, ConversationRole.USER)


class _RecordingAssembler:
    def __init__(self, delegate: ContextAssembler) -> None:
        self._delegate = delegate
        self.assemblies = []

    def assemble(self, query, budget, *, llm_log=None):
        assembly = self._delegate.assemble(query, budget, llm_log=llm_log)
        self.assemblies.append(assembly)
        return assembly


class _Summarizer:
    def __init__(self) -> None:
        self.calls = []

    def summarize(self, previous_summary, contiguous_turns, budget, *, llm_log=None):
        self.calls.append((previous_summary, contiguous_turns, budget))
        return ContextSummaryOutput(
            f"summary through {contiguous_turns[-1].sequence}",
            "fixture",
            "deterministic",
        )


class _RecordingModel:
    def __init__(self) -> None:
        self.inputs = []

    def decide(self, model_input, *, llm_log=None):
        self.inputs.append(model_input)
        return FinalAnswerDecision(
            f"completed:{model_input.plan_step.step_id}"
            if model_input.plan_step is not None
            else "completed"
        )


class _ContextAwareModel(_RecordingModel):
    def __init__(self, expected: str) -> None:
        super().__init__()
        self.expected = expected

    def decide(self, model_input, *, llm_log=None):
        self.inputs.append(model_input)
        contents = [item.content for item in model_input.context_contributions]
        return FinalAnswerDecision(
            f"remembered:{self.expected}" if self.expected in contents else "not remembered"
        )


class _ToolModel:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, model_input, *, llm_log=None):
        self.calls += 1
        if model_input.observations:
            return FinalAnswerDecision("tool completed")
        return ToolActionDecision(ToolCall("call_counter", "fixture.counter", {}))


class _Intent:
    def __init__(self, intent_type: IntentType = IntentType.CHAT) -> None:
        self.intent_type = intent_type

    def classify(self, request):
        return IntentDecision(self.intent_type, 1.0)


class _Policy:
    def evaluate(self, request, intent):
        return PolicyDecision(PolicyAction.ALLOW, allowed_effects=["read"])


class _CountingSkillClient:
    def __init__(self) -> None:
        self.calls = 0

    def select(
        self,
        request,
        skill_metadata: tuple[SkillDefinition, ...],
        *,
        llm_log=None,
    ):
        self.calls += 1
        return {"selected_skill_ids": [], "reason": "fixture"}


class _RepositoryDelegate:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    def append_turn(self, turn):
        return self.delegate.append_turn(turn)

    def load_turns(self, session_id, before_or_at_sequence, limit):
        return self.delegate.load_turns(session_id, before_or_at_sequence, limit)

    def append_summary(self, summary):
        return self.delegate.append_summary(summary)

    def load_latest_valid_summary(self, session_id):
        return self.delegate.load_latest_valid_summary(session_id)


class _AssemblerReadFailureRepository(_RepositoryDelegate):
    def __init__(self, delegate) -> None:
        super().__init__(delegate)
        self.load_calls = 0

    def load_turns(self, session_id, before_or_at_sequence, limit):
        self.load_calls += 1
        if self.load_calls == 2:
            raise ConversationRepositoryError(
                "history unavailable",
                code=ContextErrorCode.HISTORY_READ_FAILED,
            )
        return super().load_turns(session_id, before_or_at_sequence, limit)


class _AssistantAppendFailureRepository(_RepositoryDelegate):
    def append_turn(self, turn):
        if turn.role == ConversationRole.ASSISTANT:
            raise ConversationRepositoryError(
                "assistant persistence unavailable",
                code=ContextErrorCode.TURN_APPEND_FAILED,
            )
        return super().append_turn(turn)


class _UserAppendFailureRepository:
    def load_turns(self, session_id, before_or_at_sequence, limit):
        return ()

    def append_turn(self, turn):
        raise ConversationRepositoryError(
            "user persistence unavailable",
            code=ContextErrorCode.TURN_APPEND_FAILED,
        )

    def append_summary(self, summary):
        raise AssertionError("summary should not be written")

    def load_latest_valid_summary(self, session_id):
        return None


def _direct_service(
    root: Path,
    model,
    *,
    repository=None,
    summarizer=None,
    budget: ContextBudget | None = None,
    skill_service=None,
    execution_scope_factory=None,
):
    repository = repository or JsonlConversationRepository(root)
    summarizer = summarizer or _Summarizer()
    assembler = _RecordingAssembler(
        ContextAssembler(repository, RollingSummaryService(repository, summarizer))
    )
    service = RuntimeService(
        skill_service or create_test_skill_service(),
        intent_service=_Intent(),
        policy_service=_Policy(),
        execution_scope_factory=execution_scope_factory
        or (lambda: ToolRuntime.from_registry(ToolRegistry())),
        executor=ReactExecutor(model),
        conversation_repository=repository,
        context_assembler=assembler,
        context_budget=budget or _budget(),
    )
    return service, repository, assembler


def _planning_service(
    root: Path,
    repository,
    conn,
    *,
    step_count: int,
    summarizer=None,
    budget: ContextBudget | None = None,
    executor_model=None,
    log_root: Path | None = None,
):
    limits = PlanningLimits(max_plan_steps=4)
    draft = PlanDraft(
        tuple(
            PlanStepDraft(
                f"step_{index}",
                index,
                f"objective {index}",
                f"outcome {index}",
                (() if index == 1 else (f"step_{index - 1}",)),
            )
            for index in range(1, step_count + 1)
        )
    )
    planner = FakePlannerModelClient(draft)
    plan_repository = SqlitePlanRepository(conn)
    planning_service = PlanningService(planner, plan_repository, limits=limits)
    executor = ReactExecutor(executor_model or _RecordingModel())
    controller = PlanController(
        plan_repository,
        executor,
        limits=limits,
        planner=planner,
        finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("plan completed")),
    )
    summarizer = summarizer or _Summarizer()
    assembler = _RecordingAssembler(
        ContextAssembler(repository, RollingSummaryService(repository, summarizer))
    )
    service = RuntimeService(
        create_test_skill_service(),
        intent_service=_Intent(IntentType.PLAN_REQUEST),
        policy_service=_Policy(),
        execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
        executor=executor,
        planning_route_client=FakePlanningRouteClient(PlanRoute("multi-step")),
        planning_service=planning_service,
        plan_controller=controller,
        planning_limits=limits,
        conversation_repository=repository,
        context_assembler=assembler,
        context_budget=budget or _budget(),
        log_root=log_root,
    )
    return service, planner, plan_repository, assembler


def _budget(*, max_recent_turns: int = 4) -> ContextBudget:
    return ContextBudget(
        max_total_tokens=200,
        max_recent_turns=max_recent_turns,
        max_summary_tokens=30,
        max_profile_tokens=0,
        max_memory_items=0,
        max_memory_tokens=0,
        max_current_input_tokens=80,
    )


def _request(text: str, number: int) -> RuntimeRequest:
    return RuntimeRequest(
        text,
        "session_e2e",
        turn_id=f"turn_{number}",
        run_id=f"run_{number}",
    )


def _append_visible_pair(repository, content: str) -> None:
    repository.append_turn(
        ConversationTurn(
            1,
            "session_e2e",
            "history_user",
            1,
            ConversationRole.USER,
            ConversationTurnKind.NATURAL_INPUT,
            content,
            "history_run",
            "2026-07-16T00:00:00Z",
        )
    )
    repository.append_turn(
        ConversationTurn(
            1,
            "session_e2e",
            "history_assistant",
            2,
            ConversationRole.ASSISTANT,
            ConversationTurnKind.FINAL_ANSWER,
            "acknowledged",
            "history_run",
            "2026-07-16T00:00:01Z",
        )
    )


def _counter_runtime(counter: dict[str, int]) -> ToolRuntime:
    definition = ToolDefinition(
        "fixture.counter",
        "Increment a deterministic test counter.",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        ToolEffect.READ,
        ToolRisk.LOW,
    )

    def handler(call: ToolCall) -> ToolResult:
        counter["calls"] += 1
        return ToolResult(
            call.call_id,
            call.tool_name,
            ToolCallStatus.SUCCEEDED,
            {"count": counter["calls"]},
        )

    return ToolRuntime.from_registry(ToolRegistry(((definition, handler),)))


if __name__ == "__main__":
    unittest.main()
