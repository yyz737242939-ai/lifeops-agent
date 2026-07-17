from __future__ import annotations

import unittest

from app.context.models import (
    ContextAssembly,
    ContextContribution,
    ContextContributionKind,
    ContextProvenance,
    ContextQuery,
    ContextQueryOrigin,
    ContextReport,
)
from app.executor.adapters import (
    AssemblyExecutorContextProvider,
    AssemblyExecutorMemoryProvider,
)
from app.executor.models import FinalAnswerDecision
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
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
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.executor_fakes import FakeExecutorModelClient
from tests.helpers import create_test_connection, create_test_skill_service


class ContextExecutorProjectionTest(unittest.TestCase):
    def test_adapters_split_conversation_from_profile_memory_and_bind_identity(self) -> None:
        request = _request("run_1", "turn_1")
        assembly = _assembly(request, "assembly_1")
        context = AssemblyExecutorContextProvider(assembly)
        memory = AssemblyExecutorMemoryProvider(assembly)

        context_values = context.load(request)
        memory_values = memory.load(request)

        self.assertEqual(len(context_values), 1)
        self.assertEqual(len(memory_values), 2)
        self.assertTrue(all("assembly_1" in item.source for item in context_values))
        self.assertTrue(all("assembly_1" in item.source for item in memory_values))
        self.assertEqual(context.assembly_id, memory.assembly_id)
        with self.assertRaises(ValueError):
            context.load(_request("other_run", "other_turn"))

    def test_direct_executor_receives_projection_from_orchestration_context(self) -> None:
        model = FakeExecutorModelClient([FinalAnswerDecision("done")])
        executor = ReactExecutor(model)
        orchestrator = RuntimeOrchestrator(
            create_test_skill_service(),
            intent_service=_Intent(),
            policy_service=_Policy(),
            execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
            executor=executor,
        )
        request = _request("run_direct", "turn_direct")
        assembly = _assembly(request, "assembly_direct")

        result = orchestrator.handle(request, context_assembly=assembly)

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertEqual(len(model.inputs), 1)
        self.assertTrue(
            all(
                "assembly_direct" in item.source
                for item in model.inputs[0].context_contributions
                + model.inputs[0].memory_contributions
            )
        )

    def test_confirmed_multi_step_plan_reuses_one_assembly_for_every_step(self) -> None:
        conn = create_test_connection()
        try:
            limits = PlanningLimits(max_plan_steps=3)
            repository = SqlitePlanRepository(conn)
            planner = FakePlannerModelClient(
                PlanDraft(
                    (
                        PlanStepDraft("step_1", 1, "读取", "获得资料"),
                        PlanStepDraft(
                            "step_2",
                            2,
                            "整理",
                            "获得摘要",
                            ("step_1",),
                        ),
                    )
                )
            )
            model = FakeExecutorModelClient(
                [FinalAnswerDecision("one"), FinalAnswerDecision("two")]
            )
            executor = ReactExecutor(model)
            planning_service = PlanningService(planner, repository, limits=limits)
            controller = PlanController(
                repository,
                executor,
                limits=limits,
                planner=planner,
                finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("complete")),
            )
            orchestrator = RuntimeOrchestrator(
                create_test_skill_service(),
                intent_service=_Intent(),
                policy_service=_Policy(),
                execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
                executor=executor,
                planning_route_client=FakePlanningRouteClient(PlanRoute("multi_step")),
                planning_service=planning_service,
                plan_controller=controller,
                planning_limits=limits,
            )
            preview_request = _request("run_preview", "turn_preview")
            preview = orchestrator.handle(
                preview_request,
                context_assembly=_assembly(preview_request, "assembly_preview"),
            )
            confirm_request = _request("run_confirm", "turn_confirm")
            confirm_assembly = _assembly(
                confirm_request,
                "assembly_confirm",
                origin=ContextQueryOrigin.CONFIRMED_PLAN_GOAL,
            )
            command = PlanCommand(
                "command_1",
                preview.tool_result["plan_id"],
                "session_1",
                preview.tool_result["revision"],
                PlanCommandAction.CONFIRM,
            )

            result = orchestrator.invoke_plan_command(
                confirm_request,
                command,
                context_assembly=confirm_assembly,
            )["result"]

            self.assertEqual(result.status, RuntimeStatus.OK)
            self.assertEqual(len(model.inputs), 2)
            self.assertEqual(
                [item.plan_step.step_id for item in model.inputs],
                ["step_1", "step_2"],
            )
            for model_input in model.inputs:
                projected = (
                    model_input.context_contributions
                    + model_input.memory_contributions
                )
                self.assertTrue(projected)
                self.assertTrue(
                    all("assembly_confirm" in item.source for item in projected)
                )
        finally:
            conn.close()


class _Intent:
    def classify(self, request):
        return IntentDecision(IntentType.PLAN_REQUEST, 1.0)


class _Policy:
    def evaluate(self, request, intent):
        return PolicyDecision(PolicyAction.ALLOW)


def _request(run_id: str, turn_id: str) -> RuntimeRequest:
    return RuntimeRequest(
        "完成多步 Context 工作",
        "session_1",
        turn_id=turn_id,
        run_id=run_id,
    )


def _assembly(
    request: RuntimeRequest,
    assembly_id: str,
    *,
    origin: ContextQueryOrigin = ContextQueryOrigin.CURRENT_USER_GOAL,
) -> ContextAssembly:
    query = ContextQuery(
        request.user_input,
        origin,
        request.session_id,
        request.run_id,
        request.turn_id,
    )
    contributions = (
        ContextContribution(
            ContextContributionKind.CONVERSATION_TURN,
            "conversation.turn",
            "earlier",
            2,
            ContextProvenance("conversation://session_1/earlier"),
        ),
        ContextContribution(
            ContextContributionKind.CURRENT_INPUT,
            "conversation.current_input",
            request.user_input,
            4,
            ContextProvenance(f"conversation://session_1/{request.turn_id}"),
        ),
        ContextContribution(
            ContextContributionKind.PROFILE,
            "profile",
            "profile value",
            2,
            ContextProvenance("profile://fixed"),
        ),
        ContextContribution(
            ContextContributionKind.MEMORY,
            "memory",
            "memory value",
            2,
            ContextProvenance("memory://1"),
        ),
    )
    report = ContextReport(
        assembly_id,
        1,
        None,
        None,
        True,
        1,
        1,
        (),
        (),
        (),
        request.created_at,
    )
    return ContextAssembly(
        assembly_id,
        request.session_id,
        request.run_id,
        request.turn_id,
        query,
        contributions,
        10,
        report,
    )


if __name__ == "__main__":
    unittest.main()
