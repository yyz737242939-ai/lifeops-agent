"""Trusted deterministic compositions for the local compiled Eval datasets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.evals.adapters import PlanLifecycleFactSource
from app.evals.graders import default_grader_registry
from app.evals.models import EvalExecutionMode
from app.evals.runner import EvalReportSink, EvalRunner
from app.evals.state import EvalStateProbeRegistry
from app.evals.targets import (
    EvalFactProviderFactory,
    EvalTargetExecutorFactory,
    EvalTargetResult,
    PlanCommandActionInvocation,
    PlanCommandSequenceTargetExecutor,
    RecoveryTargetExecutor,
    RuntimeRequestTargetExecutor,
)
from app.evals.workspace import EvalWorkspaceFactory
from app.executor.models import (
    FinalAnswerActionClaim,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    ToolActionDecision,
)
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.observability.trace_models import TraceRecord
from app.observability.trace_serialization import deserialize_record
from app.planning.controller import PlanController
from app.planning.finalizer import FakePlanFinalizerClient
from app.planning.models import (
    PlanCommandAction,
    PlanCommand,
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
from app.recovery.collector import RequestExecutionFeedbackCollector
from app.recovery.finalizer import RuntimeOutcomeFinalizer
from app.recovery.reporting import ExecutionFeedbackFactSource, RecoveryResultFactSource
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.recovery.runtime import RecoveryRuntime
from app.runtime.models import RuntimeRequest
from app.runtime.service import RuntimeService
from app.runtime_reporting import CompositeRuntimeFactProvider, EmptyRuntimeFactProvider
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.models import (
    ConfirmedAction,
    ExecutionEvidence,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolError,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL_MANIFEST_ROOT = _REPO_ROOT / "evals" / "manifests"
FIXTURE_REFS = (
    "direct-final-only",
    "direct-read-success",
    "direct-write-confirmed",
    "direct-failure-false-success",
    "direct-deny-zero-write",
    "planning-preview",
    "planning-confirm",
    "planning-partial",
    "recovery-restart",
    "serial-diamond",
    "regression-false-success",
)
STATE_PROBE_ID = "fixture-state"


def build_compiled_eval_runner(
    *,
    workspace_root: Path | None = None,
    report_sink: EvalReportSink | None = None,
) -> EvalRunner:
    compositions = {ref: _FixtureComposition(ref) for ref in FIXTURE_REFS}
    return EvalRunner(
        workspace_factory=EvalWorkspaceFactory(workspace_root),
        target_factory=EvalTargetExecutorFactory(
            {ref: _TargetBuilder(owner) for ref, owner in compositions.items()}
        ),
        fact_provider_factory=EvalFactProviderFactory(
            {ref: _FactBuilder(owner) for ref, owner in compositions.items()}
        ),
        grader_registry=default_grader_registry(),
        state_probe_registry=EvalStateProbeRegistry((_FixtureStateProbe(),)),
        state_probe_ids={ref: (STATE_PROBE_ID,) for ref in FIXTURE_REFS},
        report_sink=report_sink,
        environment_fingerprint="compiled-offline-v1",
    )


class _TargetBuilder:
    def __init__(self, owner: "_FixtureComposition") -> None:
        self._owner = owner

    def build(self, case, workspace):
        return self._owner.build_target(case, workspace)


class _FactBuilder:
    def __init__(self, owner: "_FixtureComposition") -> None:
        self._owner = owner

    def build(self, case, workspace, target):
        return self._owner.build_facts(workspace, target)


class _FixtureComposition:
    def __init__(self, fixture_ref: str) -> None:
        self._fixture_ref = fixture_ref
        self._providers: dict[Path, object] = {}

    def build_target(self, case, workspace):
        if case.fixture_ref != self._fixture_ref:
            raise ValueError("Compiled fixture identity mismatch.")
        if self._fixture_ref == "serial-diamond":
            self._providers[workspace.paths.root] = EmptyRuntimeFactProvider()
            return _SerialDiamondTarget(workspace.paths.log_root)
        if self._fixture_ref == "recovery-restart":
            return self._build_recovery(workspace)
        if self._fixture_ref.startswith("planning-"):
            return self._build_planning(workspace)
        return self._build_direct(workspace)

    def build_facts(self, workspace, target):
        provider = self._providers.pop(workspace.paths.root, None)
        if provider is None:
            raise ValueError("Compiled fact provider is unavailable for the workspace.")
        if callable(provider):
            provider = provider(target)
        return provider

    def _build_direct(self, workspace):
        root = workspace.paths.root
        conn = connect_sqlite(workspace.paths.database_path)
        migrate(conn)
        collector = RequestExecutionFeedbackCollector()
        repository = SqliteExecutionFeedbackRepository(conn)
        state_path = _state_path(root)
        decisions, intent, allowed_effects, confirmation = _direct_fixture(
            self._fixture_ref, state_path
        )
        executor = ReactExecutor(
            _ScriptedModel(decisions),
            feedback_sink=collector,
            confirmation_provider=confirmation,
        )
        service = RuntimeService(
            _skill_service(),
            intent_service=_Intent(intent),
            policy_service=_Policy(
                allowed_effects,
                action=(
                    PolicyAction.DENY
                    if self._fixture_ref == "direct-deny-zero-write"
                    else PolicyAction.ALLOW
                ),
            ),
            conn=conn,
            log_root=workspace.paths.log_root,
            execution_scope_factory=lambda: _tool_runtime(
                self._fixture_ref, state_path
            ),
            executor=executor,
            outcome_finalizer=RuntimeOutcomeFinalizer(collector, repository),
        )
        self._providers[root] = ExecutionFeedbackFactSource(repository)
        request = _request(self._fixture_ref, "direct")
        return RuntimeRequestTargetExecutor(service, request)

    def _build_planning(self, workspace):
        root = workspace.paths.root
        step_count = 3 if self._fixture_ref == "planning-partial" else 2
        decisions = (
            (FinalAnswerDecision("step one complete"), GoalNotAchievedDecision("fixture_step_failed"))
            if self._fixture_ref == "planning-partial"
            else (FinalAnswerDecision("step one complete"), FinalAnswerDecision("step two complete"))
        )
        service, plan_repository, feedback_repository = _planning_service(
            workspace, step_count=step_count, decisions=decisions
        )
        initial = _request(self._fixture_ref, "preview")
        commands = ()
        if self._fixture_ref != "planning-preview":
            commands = (
                PlanCommandActionInvocation(
                    f"command-{self._fixture_ref}",
                    PlanCommandAction.CONFIRM,
                    _request(self._fixture_ref, "confirm"),
                ),
            )
        self._providers[root] = lambda target: CompositeRuntimeFactProvider(
            (
                PlanLifecycleFactSource(plan_repository, target.plan_id),
                ExecutionFeedbackFactSource(feedback_repository),
            )
        )
        return PlanCommandSequenceTargetExecutor(service, initial, commands)

    def _build_recovery(self, workspace):
        source, _plans, _feedback = _planning_service(
            workspace,
            step_count=3,
            decisions=(
                FinalAnswerDecision("step one complete"),
                GoalNotAchievedDecision("fixture_step_failed"),
            ),
        )
        preview_request = _request(self._fixture_ref, "source-preview")
        preview = source.handle(preview_request)
        payload = preview.tool_result or {}
        command = PlanCommand(
            "command-recovery-source",
            str(payload["plan_id"]),
            preview_request.session_id,
            int(payload["revision"]),
            PlanCommandAction.CONFIRM,
        )
        source_run = _request(self._fixture_ref, "source")
        source.handle_plan_command(command, source_run)
        source.close()

        conn = connect_sqlite(workspace.paths.database_path)
        migrate(conn)
        wrapped = _IdentifiedRecoveryRuntime(
            RecoveryRuntime(conn, workspace.paths.log_root),
            workspace.paths.log_root,
        )
        resolver = _RecordedRecoveryIdentityResolver(wrapped)
        self._providers[workspace.paths.root] = lambda _target: RecoveryResultFactSource(
            wrapped.result
        )
        return RecoveryTargetExecutor(
            wrapped,
            session_id=source_run.session_id,
            source_run_id=source_run.run_id,
            identity_resolver=resolver,
        )


class _ScriptedModel:
    def __init__(self, decisions: tuple[object, ...]) -> None:
        self._decisions = list(decisions)

    def decide(self, model_input, *, llm_log=None):
        del model_input, llm_log
        if not self._decisions:
            raise AssertionError("Compiled fixture exhausted its model decisions.")
        return self._decisions.pop(0)


class _Intent:
    def __init__(self, intent_type: IntentType) -> None:
        self._intent_type = intent_type

    def classify(self, request: RuntimeRequest) -> IntentDecision:
        del request
        return IntentDecision(self._intent_type, 1.0)


class _Policy:
    def __init__(
        self,
        allowed_effects: tuple[str, ...],
        *,
        action: PolicyAction = PolicyAction.ALLOW,
    ) -> None:
        self._allowed_effects = allowed_effects
        self._action = action

    def evaluate(self, request, intent):
        del request, intent
        return PolicyDecision(self._action, allowed_effects=list(self._allowed_effects))


class _NoSkillSelectionClient:
    def select(self, request, metadata: tuple[SkillDefinition, ...], *, llm_log=None):
        del request, metadata, llm_log
        return {"selected_skill_ids": [], "reason": "Compiled fixture uses no Skill."}


def _skill_service() -> SkillService:
    return SkillService(SkillRegistry(), _NoSkillSelectionClient())


class _ExactConfirmationProvider:
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path

    def confirm(self, run_id: str, call: ToolCall, definition: ToolDefinition):
        del definition
        if _read_write_count(self._state_path) != 0:
            raise AssertionError("WRITE fixture changed state before exact confirmation.")
        return ConfirmedAction.for_call(
            run_id, call, expires_at="2099-01-01T00:00:00+00:00"
        )


def _direct_fixture(fixture_ref: str, state_path: Path):
    if fixture_ref == "direct-final-only":
        return (FinalAnswerDecision("No execution required."),), IntentType.READ, ("read",), None
    if fixture_ref == "direct-read-success":
        return (
            ToolActionDecision(ToolCall("call-read", "fixture.read", {})),
            _grounded_answer("Read completed.", "call-read", "fixture/read/call-read"),
        ), IntentType.READ, ("read",), None
    if fixture_ref == "direct-write-confirmed":
        return (
            ToolActionDecision(ToolCall("call-write", "fixture.write", {})),
            _grounded_answer("Write completed.", "call-write", "fixture/write/call-write"),
        ), IntentType.WRITE_REQUEST, ("write",), _ExactConfirmationProvider(state_path)
    if fixture_ref in ("direct-failure-false-success", "regression-false-success"):
        return (
            ToolActionDecision(ToolCall("call-failure", "fixture.read", {})),
            _grounded_answer("Everything succeeded.", "call-failure"),
        ), IntentType.READ, ("read",), None
    if fixture_ref == "direct-deny-zero-write":
        return (
            ToolActionDecision(ToolCall("call-denied", "fixture.write", {})),
        ), IntentType.WRITE_REQUEST, (), None
    raise ValueError("Unknown Direct compiled fixture.")


def _grounded_answer(message: str, call_id: str, *references: str):
    return FinalAnswerDecision(
        message,
        (FinalAnswerActionClaim(f"claim-{call_id}", call_id, tuple(references)),),
    )


def _tool_runtime(fixture_ref: str, state_path: Path) -> ToolRuntime:
    read = _definition("fixture.read", ToolEffect.READ)
    write = _definition("fixture.write", ToolEffect.WRITE)

    def read_handler(call: ToolCall) -> ToolResult:
        if fixture_ref in ("direct-failure-false-success", "regression-false-success"):
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.FAILED,
                error=ToolError("fixture_failed", "Synthetic read failure.", False),
            )
        return ToolResult(
            call.call_id,
            call.tool_name,
            ToolCallStatus.SUCCEEDED,
            {"ok": True},
            (ExecutionEvidence("fixture_read", "Synthetic read completed.", f"fixture/read/{call.call_id}"),),
        )

    def write_handler(call: ToolCall) -> ToolResult:
        if fixture_ref == "direct-deny-zero-write":
            raise AssertionError("Denied WRITE handler must not be reached.")
        count = _read_write_count(state_path) + 1
        state_path.write_text(json.dumps({"write_count": count}), encoding="utf-8")
        return ToolResult(
            call.call_id,
            call.tool_name,
            ToolCallStatus.SUCCEEDED,
            {"ok": True},
            (ExecutionEvidence("fixture_write", "Synthetic write completed.", f"fixture/write/{call.call_id}"),),
        )

    return ToolRuntime.from_registry(ToolRegistry(((read, read_handler), (write, write_handler))))


def _definition(name: str, effect: ToolEffect) -> ToolDefinition:
    return ToolDefinition(
        name,
        "Operate on an isolated compiled fixture.",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        effect,
        ToolRisk.LOW if effect is ToolEffect.READ else ToolRisk.MEDIUM,
    )


def _planning_service(workspace, *, step_count: int, decisions: tuple[object, ...]):
    conn = connect_sqlite(workspace.paths.database_path)
    migrate(conn)
    plan_repository = SqlitePlanRepository(conn)
    feedback_repository = SqliteExecutionFeedbackRepository(conn)
    collector = RequestExecutionFeedbackCollector()
    limits = PlanningLimits(max_plan_steps=4)
    draft = PlanDraft(
        tuple(
            PlanStepDraft(
                f"step-{position}",
                position,
                f"objective {position}",
                f"outcome {position}",
                () if position == 1 else (f"step-{position - 1}",),
            )
            for position in range(1, step_count + 1)
        )
    )
    planner = FakePlannerModelClient(draft)
    executor = ReactExecutor(_ScriptedModel(decisions), feedback_sink=collector)
    service = RuntimeService(
        _skill_service(),
        intent_service=_Intent(IntentType.PLAN_REQUEST),
        policy_service=_Policy(("read",)),
        conn=conn,
        log_root=workspace.paths.log_root,
        execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
        executor=executor,
        planning_route_client=FakePlanningRouteClient(PlanRoute("compiled_multi_step")),
        planning_service=PlanningService(planner, plan_repository, limits=limits),
        plan_controller=PlanController(
            plan_repository,
            executor,
            limits=limits,
            planner=planner,
            finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("Compiled plan complete.")),
        ),
        planning_limits=limits,
        outcome_finalizer=RuntimeOutcomeFinalizer(
            collector, feedback_repository, plan_repository=plan_repository
        ),
    )
    return service, plan_repository, feedback_repository


class _IdentifiedRecoveryRuntime:
    def __init__(self, delegate: RecoveryRuntime, log_root: Path) -> None:
        self._delegate = delegate
        self._log_root = log_root
        self.identity: tuple[str, str] | None = None
        self.result = None

    def explain(self, session_id: str, run_id: str | None = None):
        before = {item[0] for item in _trace_identities(self._log_root)}
        self.result = self._delegate.explain(session_id, run_id)
        created = [item for item in _trace_identities(self._log_root) if item[0] not in before]
        if len(created) != 1:
            raise ValueError("Recovery fixture must create exactly one new trace.")
        _trace_id, recovery_run_id, turn_id = created[0]
        self.identity = recovery_run_id, turn_id
        return self.result

    def close(self) -> None:
        self._delegate.close()


class _RecordedRecoveryIdentityResolver:
    def __init__(self, runtime: _IdentifiedRecoveryRuntime) -> None:
        self._runtime = runtime

    def resolve(self, result):
        if result is not self._runtime.result or self._runtime.identity is None:
            raise ValueError("Recovery identity was not recorded.")
        return self._runtime.identity


def _trace_identities(log_root: Path) -> tuple[tuple[str, str, str], ...]:
    identities = []
    for path in sorted(log_root.rglob("traces.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = deserialize_record(json.loads(line))
            if isinstance(record, TraceRecord):
                identities.append((record.trace_id, record.run_id, record.turn_id))
    return tuple(identities)


class _SerialDiamondTarget:
    execution_mode = EvalExecutionMode.RUNTIME_REQUEST

    def __init__(self, log_root: Path) -> None:
        self._log_root = log_root

    def execute(self) -> EvalTargetResult:
        source = _REPO_ROOT / "tests" / "fixtures" / "traces" / "serial_diamond"
        target = self._log_root / "serial-diamond"
        target.mkdir(parents=True, exist_ok=False)
        for path in source.iterdir():
            if path.is_file():
                shutil.copy2(path, target / path.name)
        return EvalTargetResult(
            self.execution_mode,
            "run_diamond",
            "session_diamond",
            "turn_diamond",
            ("run_diamond",),
        )

    def close(self) -> None:
        return None


class _FixtureStateProbe:
    probe_id = STATE_PROBE_ID

    def read(self, workspace):
        return {"write_count": _read_write_count(_state_path(workspace.root))}


def _state_path(root: Path) -> Path:
    return root / "data" / "fixture_state.json"


def _read_write_count(path: Path) -> int:
    if not path.is_file():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("write_count")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Compiled fixture state is invalid.")
    return value


def _request(fixture_ref: str, phase: str) -> RuntimeRequest:
    token = f"{fixture_ref}-{phase}"
    return RuntimeRequest(
        f"Run deterministic fixture {fixture_ref}.",
        f"session-{fixture_ref}",
        turn_id=f"turn-{token}",
        run_id=f"run-{token}",
    )
