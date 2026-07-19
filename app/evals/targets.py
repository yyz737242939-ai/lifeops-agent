"""Trusted target factories and adapters over existing public runtime methods."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.common.validation import require_non_empty_string
from app.evals.models import EvalCase, EvalExecutionMode, require_stable_eval_id
from app.evals.workspace import EvalWorkspace
from app.planning.models import PlanCommand, PlanCommandAction
from app.recovery.models import RecoveryResult
from app.runtime.models import RuntimeRequest, RuntimeResult
from app.runtime_reporting import RuntimeFactProvider


@dataclass(frozen=True)
class EvalTargetResult:
    execution_mode: EvalExecutionMode
    run_id: str
    session_id: str
    turn_id: str
    run_ids: tuple[str, ...]
    plan_id: str | None = None
    source_run_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution_mode, EvalExecutionMode):
            raise ValueError("execution_mode must be EvalExecutionMode.")
        for name in ("run_id", "session_id", "turn_id"):
            require_non_empty_string(getattr(self, name), name)
        if not isinstance(self.run_ids, tuple) or not self.run_ids:
            raise ValueError("run_ids must be a non-empty tuple.")
        for run_id in self.run_ids:
            require_non_empty_string(run_id, "run_ids")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("run_ids must not contain duplicates.")
        if self.run_id != self.run_ids[-1]:
            raise ValueError("run_id must identify the final target run.")
        for name in ("plan_id", "source_run_id"):
            value = getattr(self, name)
            if value is not None:
                require_non_empty_string(value, name)


class EvalTargetExecutor(Protocol):
    @property
    def execution_mode(self) -> EvalExecutionMode: ...

    def execute(self) -> EvalTargetResult: ...

    def close(self) -> None: ...


class EvalTargetBuilder(Protocol):
    def build(self, case: EvalCase, workspace: EvalWorkspace) -> EvalTargetExecutor: ...


class EvalFactProviderBuilder(Protocol):
    def build(
        self,
        case: EvalCase,
        workspace: EvalWorkspace,
        target: EvalTargetResult,
    ) -> RuntimeFactProvider: ...


class EvalTargetExecutorFactory:
    """Select only code-registered builders; manifests never name imports/callables."""

    def __init__(
        self,
        builders: Mapping[str, EvalTargetBuilder],
    ) -> None:
        self._builders = _validated_builders(builders, "target builders")

    def create(self, case: EvalCase, workspace: EvalWorkspace) -> EvalTargetExecutor:
        key = _composition_key(case)
        try:
            builder = self._builders[key]
        except KeyError as exc:
            raise ValueError("No trusted target builder is registered for the case.") from exc
        executor = builder.build(case, workspace)
        if executor.execution_mode is not case.execution_mode:
            raise ValueError("Target builder returned the wrong execution mode.")
        return executor


class EvalFactProviderFactory:
    def __init__(self, builders: Mapping[str, EvalFactProviderBuilder]) -> None:
        self._builders = _validated_builders(builders, "fact provider builders")

    def create(
        self,
        case: EvalCase,
        workspace: EvalWorkspace,
        target: EvalTargetResult,
    ) -> RuntimeFactProvider:
        key = _composition_key(case)
        try:
            builder = self._builders[key]
        except KeyError as exc:
            raise ValueError("No trusted fact provider builder is registered for the case.") from exc
        return builder.build(case, workspace, target)


class RuntimeServicePort(Protocol):
    def handle(self, request: RuntimeRequest) -> RuntimeResult: ...

    def handle_plan_command(
        self, command: PlanCommand, request: RuntimeRequest
    ) -> RuntimeResult: ...

    def close(self) -> None: ...


class RecoveryRuntimePort(Protocol):
    def explain(self, session_id: str, run_id: str | None = None) -> RecoveryResult: ...

    def close(self) -> None: ...


class RecoveryTraceIdentityResolver(Protocol):
    def resolve(self, result: RecoveryResult) -> tuple[str, str]: ...


class RuntimeRequestTargetExecutor:
    execution_mode = EvalExecutionMode.RUNTIME_REQUEST

    def __init__(self, service: RuntimeServicePort, request: RuntimeRequest) -> None:
        if not isinstance(request, RuntimeRequest):
            raise ValueError("request must be RuntimeRequest.")
        self._service = service
        self._request = request
        self._closed = False

    def execute(self) -> EvalTargetResult:
        result = self._service.handle(self._request)
        _validate_runtime_result(result, self._request)
        return EvalTargetResult(
            self.execution_mode,
            self._request.run_id,
            self._request.session_id,
            self._request.turn_id,
            (self._request.run_id,),
        )

    def close(self) -> None:
        if not self._closed:
            self._service.close()
            self._closed = True


@dataclass(frozen=True)
class PlanCommandInvocation:
    command: PlanCommand
    request: RuntimeRequest

    def __post_init__(self) -> None:
        if not isinstance(self.command, PlanCommand):
            raise ValueError("command must be PlanCommand.")
        if not isinstance(self.request, RuntimeRequest):
            raise ValueError("request must be RuntimeRequest.")
        if self.command.session_id != self.request.session_id:
            raise ValueError("command and request must share a session.")


@dataclass(frozen=True)
class PlanCommandActionInvocation:
    command_id: str
    action: PlanCommandAction
    request: RuntimeRequest
    feedback: str | None = None

    def __post_init__(self) -> None:
        require_stable_eval_id(self.command_id, "command_id")
        if not isinstance(self.action, PlanCommandAction):
            raise ValueError("action must be PlanCommandAction.")
        if not isinstance(self.request, RuntimeRequest):
            raise ValueError("request must be RuntimeRequest.")
        if self.feedback is not None:
            require_non_empty_string(self.feedback, "feedback")


class PlanCommandSequenceTargetExecutor:
    execution_mode = EvalExecutionMode.PLAN_COMMAND_SEQUENCE

    def __init__(
        self,
        service: RuntimeServicePort,
        initial_request: RuntimeRequest,
        commands: tuple[PlanCommandInvocation | PlanCommandActionInvocation, ...],
    ) -> None:
        if not isinstance(initial_request, RuntimeRequest):
            raise ValueError("initial_request must be RuntimeRequest.")
        if not isinstance(commands, tuple):
            raise ValueError("commands must be a tuple.")
        if not all(
            isinstance(item, (PlanCommandInvocation, PlanCommandActionInvocation))
            for item in commands
        ):
            raise ValueError("commands must contain typed plan invocations.")
        if any(
            item.request.session_id != initial_request.session_id for item in commands
        ):
            raise ValueError("all plan requests must share one session.")
        plan_ids = {
            item.command.plan_id
            for item in commands
            if isinstance(item, PlanCommandInvocation)
        }
        if len(plan_ids) > 1:
            raise ValueError("all plan commands must target one plan.")
        run_ids = (initial_request.run_id, *(item.request.run_id for item in commands))
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("plan sequence run IDs must be unique.")
        self._service = service
        self._initial = initial_request
        self._commands = commands
        self._closed = False

    def execute(self) -> EvalTargetResult:
        initial_result = self._service.handle(self._initial)
        _validate_runtime_result(initial_result, self._initial)
        plan_id, revision = _preview_identity(initial_result)
        for invocation in self._commands:
            command = (
                invocation.command
                if isinstance(invocation, PlanCommandInvocation)
                else PlanCommand(
                    invocation.command_id,
                    plan_id,
                    invocation.request.session_id,
                    revision,
                    invocation.action,
                    invocation.feedback,
                )
            )
            result = self._service.handle_plan_command(
                command, invocation.request
            )
            _validate_runtime_result(result, invocation.request)
            if result.tool_result is not None:
                next_revision = result.tool_result.get("revision")
                if isinstance(next_revision, int) and not isinstance(next_revision, bool):
                    revision = next_revision
        last_request = self._commands[-1].request if self._commands else self._initial
        return EvalTargetResult(
            self.execution_mode,
            last_request.run_id,
            last_request.session_id,
            last_request.turn_id,
            (self._initial.run_id, *(item.request.run_id for item in self._commands)),
            plan_id=plan_id,
        )

    def close(self) -> None:
        if not self._closed:
            self._service.close()
            self._closed = True


class RecoveryTargetExecutor:
    execution_mode = EvalExecutionMode.RECOVERY

    def __init__(
        self,
        runtime: RecoveryRuntimePort,
        *,
        session_id: str,
        source_run_id: str | None,
        identity_resolver: RecoveryTraceIdentityResolver,
    ) -> None:
        require_non_empty_string(session_id, "session_id")
        if source_run_id is not None:
            require_non_empty_string(source_run_id, "source_run_id")
        self._runtime = runtime
        self._session_id = session_id
        self._source_run_id = source_run_id
        self._identity_resolver = identity_resolver
        self._closed = False

    def execute(self) -> EvalTargetResult:
        result = self._runtime.explain(self._session_id, self._source_run_id)
        if not isinstance(result, RecoveryResult):
            raise ValueError("Recovery runtime must return RecoveryResult.")
        if result.context.session_id != self._session_id:
            raise ValueError("Recovery result session does not match its request.")
        if (
            self._source_run_id is not None
            and result.context.source_run_id != self._source_run_id
        ):
            raise ValueError("Recovery result source run does not match its request.")
        run_id, turn_id = self._identity_resolver.resolve(result)
        require_non_empty_string(run_id, "run_id")
        require_non_empty_string(turn_id, "turn_id")
        return EvalTargetResult(
            self.execution_mode,
            run_id,
            self._session_id,
            turn_id,
            (run_id,),
            source_run_id=result.context.source_run_id,
        )

    def close(self) -> None:
        if not self._closed:
            self._runtime.close()
            self._closed = True


def _validate_runtime_result(result: RuntimeResult, request: RuntimeRequest) -> None:
    if not isinstance(result, RuntimeResult):
        raise ValueError("Runtime service must return RuntimeResult.")
    if result.run_id != request.run_id or result.session_id != request.session_id:
        raise ValueError("Runtime result identity does not match its request.")


def _preview_identity(result: RuntimeResult) -> tuple[str, int]:
    payload = result.tool_result
    if not isinstance(payload, dict) or payload.get("type") != "plan_preview":
        raise ValueError("Initial plan request must return a plan preview.")
    plan_id = payload.get("plan_id")
    revision = payload.get("revision")
    require_non_empty_string(plan_id, "plan_id")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("plan preview revision must be a positive integer.")
    return plan_id, revision


def _composition_key(case: EvalCase) -> str:
    return case.fixture_ref or case.execution_mode.value


def _validated_builders(builders: Mapping[str, object], name: str) -> dict[str, object]:
    if not isinstance(builders, Mapping) or not builders:
        raise ValueError(f"{name} must be a non-empty mapping.")
    result = dict(builders)
    for key in result:
        require_stable_eval_id(key, name)
    return result
