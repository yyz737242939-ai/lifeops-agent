from __future__ import annotations

import json
import unittest

from app.context.errors import ContextErrorCode, ConversationRepositoryError
from app.context.models import (
    ContextAssembly,
    ContextBudget,
    ContextContribution,
    ContextContributionKind,
    ContextProvenance,
    ContextQuery,
    ContextQueryOrigin,
    ContextReport,
    ConversationTurnKind,
)
from app.planning.models import PlanCommand, PlanCommandAction
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.runtime.service import RuntimeService
from tests.helpers import create_test_skill_service


class ContextRuntimeLifecycleTest(unittest.TestCase):
    def test_validated_outcome_precedes_completed_event_and_assistant_turn(self) -> None:
        order: list[str] = []
        repository = _Repository(order)
        assembler = _Assembler(order)
        orchestrator = _Orchestrator(order)
        finalizer = _OutcomeFinalizer(order)
        service = _service(
            repository,
            assembler,
            orchestrator,
            outcome_finalizer=finalizer,
        )

        result = service.handle(
            RuntimeRequest("hello", "session_1", turn_id="turn_1", run_id="run_1")
        )

        self.assertEqual(result.message, "validated")
        self.assertEqual(repository.turns[-1].content, "validated")
        self.assertEqual(
            order,
            [
                "load",
                "append",
                "assemble",
                "orchestrate",
                "finalize_outcome",
                "load",
                "append",
            ],
        )

    def test_additive_finalizer_context_keeps_legacy_finalizer_compatible(self) -> None:
        order: list[str] = []
        repository = _Repository(order)
        service = _service(
            repository,
            _Assembler(order),
            _Orchestrator(order),
            outcome_finalizer=_LegacyOutcomeFinalizer(order),
        )

        result = service.handle(
            RuntimeRequest("hello", "session_1", turn_id="turn_1", run_id="run_1")
        )

        self.assertEqual(result.message, "legacy validated")
        self.assertEqual(order.count("finalize_outcome"), 1)

    def test_user_turn_is_appended_then_assembled_once_before_orchestration(self) -> None:
        order: list[str] = []
        repository = _Repository(order)
        assembler = _Assembler(order)
        orchestrator = _Orchestrator(order)
        service = _service(repository, assembler, orchestrator)
        request = RuntimeRequest(
            "继续 Context 实现",
            "session_1",
            turn_id="turn_1",
            run_id="run_1",
            created_at="2026-07-16T00:00:00Z",
        )

        result = service.handle(request)

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertEqual(
            order,
            ["load", "append", "assemble", "orchestrate", "load", "append"],
        )
        self.assertEqual(len(repository.turns), 2)
        self.assertEqual(repository.turns[0].kind, ConversationTurnKind.NATURAL_INPUT)
        self.assertEqual(repository.turns[0].content, request.user_input)
        self.assertEqual(repository.turns[1].kind, ConversationTurnKind.FINAL_ANSWER)
        self.assertEqual(repository.turns[1].content, "done")
        self.assertEqual(len(assembler.calls), 1)
        query, budget, _ = assembler.calls[0]
        self.assertEqual(query.origin, ContextQueryOrigin.CURRENT_USER_GOAL)
        self.assertEqual(orchestrator.assemblies, [assembler.output])
        self.assertEqual(budget.max_total_tokens, 100)

    def test_user_turn_append_failure_stops_before_assembly_llm_or_tool(self) -> None:
        order: list[str] = []
        repository = _Repository(order, fail_append=True)
        assembler = _Assembler(order)
        orchestrator = _Orchestrator(order)
        service = _service(repository, assembler, orchestrator)

        result = service.handle(
            RuntimeRequest("hello", "session_1", turn_id="turn_1", run_id="run_1")
        )

        self.assertEqual(result.status, RuntimeStatus.ERROR)
        self.assertEqual(result.error_code, ContextErrorCode.TURN_APPEND_FAILED.value)
        self.assertEqual(order, ["load", "append"])
        self.assertEqual(assembler.calls, [])
        self.assertEqual(orchestrator.assemblies, [])

    def test_oversized_current_input_stops_before_repository_and_orchestration(self) -> None:
        order: list[str] = []
        repository = _Repository(order)
        assembler = _Assembler(order)
        orchestrator = _Orchestrator(order)
        service = _service(repository, assembler, orchestrator)

        result = service.handle(
            RuntimeRequest("x" * 200, "session_1", turn_id="turn_1", run_id="run_1")
        )

        self.assertEqual(result.status, RuntimeStatus.ERROR)
        self.assertEqual(result.error_code, ContextErrorCode.INPUT_TOO_LARGE.value)
        self.assertEqual(result.message, "Current input is too large.")
        self.assertEqual(order, [])
        self.assertEqual(repository.turns, [])
        self.assertEqual(assembler.calls, [])
        self.assertEqual(orchestrator.assemblies, [])

    def test_plan_command_stores_safe_command_but_queries_durable_goal(self) -> None:
        order: list[str] = []
        repository = _Repository(order)
        assembler = _Assembler(order)
        orchestrator = _Orchestrator(order)
        service = _service(repository, assembler, orchestrator)
        request = RuntimeRequest(
            "完成 Context 模块",
            "session_1",
            turn_id="turn_1",
            run_id="run_1",
        )
        command = PlanCommand(
            "command_1",
            "plan_1",
            "session_1",
            1,
            PlanCommandAction.CONFIRM,
        )

        result = service.handle_plan_command(command, request)

        self.assertEqual(result.status, RuntimeStatus.OK)
        stored = repository.turns[0]
        self.assertEqual(stored.kind, ConversationTurnKind.PLAN_COMMAND)
        self.assertEqual(json.loads(stored.content)["action"], "confirm")
        query = assembler.calls[0][0]
        self.assertEqual(query.text, request.user_input)
        self.assertEqual(query.origin, ContextQueryOrigin.CONFIRMED_PLAN_GOAL)
        self.assertEqual(orchestrator.assemblies, [assembler.output])
        self.assertEqual(repository.turns[1].kind, ConversationTurnKind.FINAL_ANSWER)

    def test_only_visible_plan_preview_is_persisted(self) -> None:
        order: list[str] = []
        repository = _Repository(order)
        assembler = _Assembler(order)
        orchestrator = _Orchestrator(order)
        orchestrator.result = RuntimeResult(
            "run_1",
            "session_1",
            RuntimeStatus.REQUIRES_CONFIRMATION,
            "请确认计划",
            tool_result={"type": "plan_preview", "plan_id": "plan_1"},
        )
        service = _service(repository, assembler, orchestrator)

        service.handle(
            RuntimeRequest("制定计划", "session_1", turn_id="turn_1", run_id="run_1")
        )

        stored = repository.turns[1]
        self.assertEqual(stored.kind, ConversationTurnKind.PLAN_PREVIEW)
        payload = json.loads(stored.content)
        self.assertEqual(payload["message"], "请确认计划")
        self.assertEqual(payload["tool_result"]["plan_id"], "plan_1")
        self.assertNotIn("internal model response", stored.content)
        self.assertNotIn("internal tool response", stored.content)

    def test_visible_planning_results_map_to_frozen_assistant_kinds(self) -> None:
        cases = (
            (
                "planning_clarification",
                ConversationTurnKind.CLARIFICATION,
                "Which date should I use?",
            ),
            (
                "plan_result",
                ConversationTurnKind.COMMAND_RESULT,
                "Plan cancelled.",
            ),
        )
        for result_type, expected_kind, message in cases:
            with self.subTest(result_type=result_type):
                order: list[str] = []
                repository = _Repository(order)
                assembler = _Assembler(order)
                orchestrator = _Orchestrator(order)
                orchestrator.result = RuntimeResult(
                    "run_1",
                    "session_1",
                    RuntimeStatus.REQUIRES_CONFIRMATION,
                    message,
                    tool_result={"type": result_type},
                )
                service = _service(repository, assembler, orchestrator)

                service.handle(
                    RuntimeRequest(
                        "continue",
                        "session_1",
                        turn_id="turn_1",
                        run_id="run_1",
                    )
                )

                stored = repository.turns[1]
                self.assertEqual(stored.kind, expected_kind)
                self.assertEqual(json.loads(stored.content)["message"], message)

    def test_assistant_append_failure_keeps_visible_runtime_result(self) -> None:
        order: list[str] = []
        repository = _Repository(order, fail_append_number=2)
        assembler = _Assembler(order)
        orchestrator = _Orchestrator(order)
        service = _service(repository, assembler, orchestrator)

        result = service.handle(
            RuntimeRequest("hello", "session_1", turn_id="turn_1", run_id="run_1")
        )

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertEqual(result.message, "done")
        self.assertEqual(len(repository.turns), 1)
        self.assertEqual(order[-3:], ["orchestrate", "load", "append"])


class _Repository:
    def __init__(
        self,
        order: list[str],
        *,
        fail_append: bool = False,
        fail_append_number: int | None = None,
    ) -> None:
        self.order = order
        self.fail_append = fail_append
        self.fail_append_number = fail_append_number
        self.append_count = 0
        self.turns = []

    def load_turns(self, session_id, before_or_at_sequence, limit):
        self.order.append("load")
        return tuple(self.turns)

    def append_turn(self, turn):
        self.order.append("append")
        self.append_count += 1
        if self.fail_append or self.append_count == self.fail_append_number:
            raise ConversationRepositoryError(
                "Safe append failure.",
                code=ContextErrorCode.TURN_APPEND_FAILED,
            )
        self.turns.append(turn)

    def append_summary(self, summary):
        raise AssertionError("summary append is not expected")

    def load_latest_valid_summary(self, session_id):
        return None


class _Assembler:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls = []
        self.output = None

    def assemble(self, query, budget, *, llm_log=None):
        self.order.append("assemble")
        self.calls.append((query, budget, llm_log))
        self.output = _assembly(query)
        return self.output


class _Orchestrator:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.assemblies = []
        self.result = None

    def invoke(self, request, trace=None, llm_log=None, context_assembly=None):
        self.order.append("orchestrate")
        self.assemblies.append(context_assembly)
        return {
            "result": self.result
            or RuntimeResult(
                request.run_id, request.session_id, RuntimeStatus.OK, "done"
            ),
            "error_stage": None,
        }

    def invoke_plan_command(
        self,
        request,
        command,
        trace=None,
        llm_log=None,
        context_assembly=None,
    ):
        self.order.append("orchestrate")
        self.assemblies.append(context_assembly)
        return {
            "result": self.result
            or RuntimeResult(
                request.run_id, request.session_id, RuntimeStatus.OK, "done"
            ),
            "error_stage": None,
        }


class _OutcomeFinalizer:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def finalize(
        self,
        request,
        draft,
        *,
        trace_id,
        trace=None,
        gate_outcome=None,
        plan_finalizer_output=None,
    ):
        self.order.append("finalize_outcome")
        return RuntimeResult(
            draft.run_id,
            draft.session_id,
            draft.status,
            "validated",
            draft.tool_result,
            draft.error_code,
        )


class _LegacyOutcomeFinalizer:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def finalize(self, request, draft, *, trace_id):
        self.order.append("finalize_outcome")
        return RuntimeResult(
            draft.run_id,
            draft.session_id,
            draft.status,
            "legacy validated",
            draft.tool_result,
            draft.error_code,
        )


def _service(
    repository,
    assembler,
    orchestrator,
    *,
    outcome_finalizer=None,
) -> RuntimeService:
    service = RuntimeService(
        create_test_skill_service(),
        conversation_repository=repository,
        context_assembler=assembler,
        context_budget=ContextBudget(100, 4, 20, 0, 0, 0, 40),
        outcome_finalizer=outcome_finalizer,
    )
    service._orchestrator = orchestrator
    return service


def _assembly(query: ContextQuery) -> ContextAssembly:
    contribution = ContextContribution(
        ContextContributionKind.CURRENT_INPUT,
        "conversation.current_input",
        query.text,
        2,
        ContextProvenance(f"conversation://{query.session_id}/{query.turn_id}"),
    )
    report = ContextReport(
        "assembly_1",
        0,
        None,
        None,
        False,
        0,
        0,
        (),
        (),
        (),
        "2026-07-16T00:00:00Z",
    )
    return ContextAssembly(
        "assembly_1",
        query.session_id,
        query.run_id,
        query.turn_id,
        query,
        (contribution,),
        2,
        report,
    )


if __name__ == "__main__":
    unittest.main()
