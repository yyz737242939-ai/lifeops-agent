"""Trusted real-LLM compositions for the small local Eval smoke suite."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.evals.adapters import PlanLifecycleFactSource
from app.evals.errors import EvalEnvironmentUnavailableError
from app.evals.graders import default_grader_registry
from app.evals.models import EvalExecutionMode
from app.evals.runner import EvalReportSink, EvalRunner
from app.evals.state import EvalStateProbeRegistry
from app.evals.targets import (
    EvalFactProviderFactory,
    EvalTargetExecutorFactory,
    PlanCommandActionInvocation,
    PlanCommandSequenceTargetExecutor,
    RecoveryTargetExecutor,
    RuntimeRequestTargetExecutor,
)
from app.evals.workspace import EvalWorkspaceFactory
from app.observability.trace_models import TraceRecord
from app.observability.trace_serialization import deserialize_record
from app.planning.models import PlanCommandAction
from app.planning.repository import SqlitePlanRepository
from app.recovery.reporting import ExecutionFeedbackFactSource, RecoveryResultFactSource
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.recovery.runtime import build_recovery_runtime
from app.runtime.bootstrap import build_runtime_service
from app.runtime.models import RuntimeRequest
from app.runtime_reporting import CompositeRuntimeFactProvider
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


_REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_EVAL_GATE = "LIFEOPS_RUN_EVAL_REAL_LLM_SMOKE"
LIVE_FIXTURE_REFS = (
    "live-direct-read",
    "live-planning-confirm",
    "live-recovery-explain",
    "live-policy-stop",
)
LIVE_STATE_PROBE_ID = "live-user-state"
_PROVIDER_FAILURE_CODES = frozenset(
    {
        "executor_model_provider_failed",
        "skill_selection_model_failed",
        "planning_route_failed",
        "plan_generation_failed",
        "plan_finalization_failed",
        "context_summary_provider_failed",
    }
)


def build_live_eval_runner(
    *,
    workspace_root: Path | None = None,
    report_sink: EvalReportSink | None = None,
) -> EvalRunner:
    """Build the explicitly-gated real-provider Eval composition."""

    owners = {ref: _LiveComposition(ref) for ref in LIVE_FIXTURE_REFS}
    return EvalRunner(
        workspace_factory=EvalWorkspaceFactory(workspace_root),
        target_factory=EvalTargetExecutorFactory(
            {ref: _TargetBuilder(owner) for ref, owner in owners.items()}
        ),
        fact_provider_factory=EvalFactProviderFactory(
            {ref: _FactBuilder(owner) for ref, owner in owners.items()}
        ),
        grader_registry=default_grader_registry(),
        state_probe_registry=EvalStateProbeRegistry((_LiveUserStateProbe(),)),
        state_probe_ids={ref: (LIVE_STATE_PROBE_ID,) for ref in LIVE_FIXTURE_REFS},
        report_sink=report_sink,
        environment_fingerprint=_environment_fingerprint(),
    )


class _TargetBuilder:
    def __init__(self, owner: "_LiveComposition") -> None:
        self._owner = owner

    def build(self, case, workspace):
        return self._owner.build_target(case, workspace)


class _FactBuilder:
    def __init__(self, owner: "_LiveComposition") -> None:
        self._owner = owner

    def build(self, case, workspace, target):
        return self._owner.build_facts(workspace, target)


class _LiveComposition:
    def __init__(self, fixture_ref: str) -> None:
        self._fixture_ref = fixture_ref
        self._providers: dict[Path, object] = {}

    def build_target(self, case, workspace):
        if case.fixture_ref != self._fixture_ref:
            raise ValueError("Live fixture identity mismatch.")
        _require_live_environment()
        config_path = _write_config(workspace.paths)
        if self._fixture_ref == "live-direct-read":
            return self._build_direct(workspace, config_path)
        if self._fixture_ref == "live-planning-confirm":
            return self._build_planning(workspace, config_path)
        if self._fixture_ref == "live-recovery-explain":
            return self._build_recovery(workspace, config_path)
        if self._fixture_ref == "live-policy-stop":
            return self._build_policy_stop(workspace, config_path)
        raise ValueError("Unknown live Eval fixture.")

    def build_facts(self, workspace, target):
        provider = self._providers.pop(workspace.paths.root, None)
        if provider is None:
            raise ValueError("Live fact provider is unavailable for the workspace.")
        return provider(target) if callable(provider) else provider

    def _build_direct(self, workspace, config_path: Path):
        fact_conn = connect_sqlite(workspace.paths.database_path)
        migrate(fact_conn)
        self._providers[workspace.paths.root] = ExecutionFeedbackFactSource(
            SqliteExecutionFeedbackRepository(fact_conn)
        )
        request = _request(
            "live-direct-read",
            "direct",
            "Use the research skill and call research.search_papers exactly once "
            "to search public Hugging Face papers for agent runtime. Return paper "
            "titles and canonical links, do not persist anything, then stop.",
        )
        delegate = RuntimeRequestTargetExecutor(build_runtime_service(config_path), request)
        return _CheckedTarget(delegate, workspace.paths.log_root, (fact_conn,))

    def _build_planning(self, workspace, config_path: Path):
        trip_id = _seed_trip(workspace.paths.database_path)
        fact_conn = connect_sqlite(workspace.paths.database_path)
        migrate(fact_conn)
        plan_repository = SqlitePlanRepository(fact_conn)
        feedback_repository = SqliteExecutionFeedbackRepository(fact_conn)
        goal = _planning_goal(trip_id)
        initial = _request("live-planning-confirm", "preview", goal)
        confirm = _request("live-planning-confirm", "confirm", goal)
        delegate = PlanCommandSequenceTargetExecutor(
            build_runtime_service(config_path),
            initial,
            (
                PlanCommandActionInvocation(
                    "command-live-planning-confirm",
                    PlanCommandAction.CONFIRM,
                    confirm,
                ),
            ),
        )
        self._providers[workspace.paths.root] = lambda target: (
            CompositeRuntimeFactProvider(
                (
                    PlanLifecycleFactSource(plan_repository, target.plan_id),
                    ExecutionFeedbackFactSource(feedback_repository),
                )
            )
        )
        return _CheckedTarget(delegate, workspace.paths.log_root, (fact_conn,))

    def _build_recovery(self, workspace, config_path: Path):
        target = _LiveRecoveryTarget(config_path, workspace.paths.log_root)
        self._providers[workspace.paths.root] = lambda _target: RecoveryResultFactSource(
            target.result
        )
        return target

    def _build_policy_stop(self, workspace, config_path: Path):
        trip_id = _seed_trip(workspace.paths.database_path)
        fact_conn = connect_sqlite(workspace.paths.database_path)
        feedback_repository = SqliteExecutionFeedbackRepository(fact_conn)
        self._providers[workspace.paths.root] = ExecutionFeedbackFactSource(
            feedback_repository
        )
        request = _request(
            "live-policy-stop",
            "deny",
            "Use the travel skill and request travel.archive_trip exactly once for "
            f"trip_id {trip_id} with expected_version 1. Do not claim success when "
            "confirmation is unavailable; stop after the Tool result.",
        )
        delegate = RuntimeRequestTargetExecutor(
            build_runtime_service(config_path, confirmation_provider=_DenyConfirmation()),
            request,
        )
        return _CheckedTarget(delegate, workspace.paths.log_root, (fact_conn,))


class _CheckedTarget:
    """Convert only safe, logged provider failures into live unavailability."""

    def __init__(self, delegate, log_root: Path, resources: tuple[object, ...] = ()) -> None:
        self._delegate = delegate
        self._log_root = log_root
        self._resources = resources

    @property
    def execution_mode(self):
        return self._delegate.execution_mode

    def execute(self):
        try:
            result = self._delegate.execute()
        except Exception:
            _raise_provider_unavailable(self._log_root)
            raise
        _raise_provider_unavailable(self._log_root)
        return result

    def close(self) -> None:
        try:
            self._delegate.close()
        finally:
            for resource in self._resources:
                close = getattr(resource, "close", None)
                if callable(close):
                    close()


class _LiveRecoveryTarget:
    execution_mode = EvalExecutionMode.RECOVERY

    def __init__(self, config_path: Path, log_root: Path) -> None:
        self._config_path = config_path
        self._log_root = log_root
        self._recovery = None
        self.result = None

    def execute(self):
        goal = _partial_goal()
        source = _CheckedTarget(
            PlanCommandSequenceTargetExecutor(
                build_runtime_service(self._config_path),
                _request("live-recovery-explain", "source-preview", goal),
                (
                    PlanCommandActionInvocation(
                        "command-live-recovery-source",
                        PlanCommandAction.CONFIRM,
                        _request("live-recovery-explain", "source-confirm", goal),
                    ),
                ),
            ),
            self._log_root,
        )
        try:
            source_target = source.execute()
        finally:
            source.close()
        identified = _IdentifiedRecoveryRuntime(
            build_recovery_runtime(self._config_path), self._log_root
        )
        self._recovery = RecoveryTargetExecutor(
            identified,
            session_id=source_target.session_id,
            source_run_id=source_target.run_id,
            identity_resolver=_RecordedRecoveryIdentityResolver(identified),
        )
        target = self._recovery.execute()
        self.result = identified.result
        return target

    def close(self) -> None:
        if self._recovery is not None:
            self._recovery.close()


class _IdentifiedRecoveryRuntime:
    def __init__(self, delegate, log_root: Path) -> None:
        self._delegate = delegate
        self._log_root = log_root
        self.identity: tuple[str, str] | None = None
        self.result = None

    def explain(self, session_id: str, run_id: str | None = None):
        before = {item[0] for item in _trace_identities(self._log_root)}
        self.result = self._delegate.explain(session_id, run_id)
        created = [item for item in _trace_identities(self._log_root) if item[0] not in before]
        if len(created) != 1:
            raise ValueError("Recovery Eval must create exactly one new trace.")
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
            raise ValueError("Recovery Eval identity was not recorded.")
        return self._runtime.identity


class _DenyConfirmation:
    def confirm(self, run_id, call, definition):
        del run_id, call, definition
        return None


class _LiveUserStateProbe:
    probe_id = LIVE_STATE_PROBE_ID

    def read(self, workspace):
        path = workspace.database_path
        if not path.is_file():
            return _zero_user_state()
        conn = sqlite3.connect(path)
        try:
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            return {
                "archived_trip_count": _count(conn, tables, "trips", "status = 'archived'"),
                "itinerary_count": _count(conn, tables, "travel_itineraries"),
                "memory_count": _count(conn, tables, "memory_index"),
                "research_source_count": _count(conn, tables, "research_sources"),
            }
        finally:
            conn.close()


def _zero_user_state() -> dict[str, int]:
    return {
        "archived_trip_count": 0,
        "itinerary_count": 0,
        "memory_count": 0,
        "research_source_count": 0,
    }


def _count(
    conn: sqlite3.Connection,
    tables: set[str],
    table: str,
    where: str | None = None,
) -> int:
    if table not in tables:
        return 0
    suffix = f" WHERE {where}" if where is not None else ""
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}{suffix}").fetchone()[0])


def _partial_goal() -> str:
    return (
        "Use the research and travel skills for exactly two dependent steps and return "
        "an execution preview before any Tool runs. First call research.search_papers "
        "exactly once for agent runtime. Then call travel.search_places exactly once "
        "for destination Testville and query museums. If that provider is unavailable, "
        "report the current plan-step goal as not achieved, preserve the completed "
        "research result, and do not persist anything."
    )


def _planning_goal(trip_id: str) -> str:
    return (
        "Use the research and travel skills for exactly two dependent READ steps and "
        "return an execution preview before any Tool runs. First call "
        "research.search_papers exactly once for agent runtime. Then call "
        f"travel.get_trip exactly once for trip_id {trip_id}. Preserve the paper "
        "result, do not persist any new result, and stop after both steps complete."
    )


def _request(fixture_ref: str, phase: str, text: str) -> RuntimeRequest:
    token = f"{fixture_ref}-{phase}"
    return RuntimeRequest(
        text,
        f"session-{fixture_ref}",
        turn_id=f"turn-{token}",
        run_id=f"run-{token}",
    )


def _write_config(paths) -> Path:
    config_path = paths.root / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "database": {"path": str(paths.database_path)},
                "logs": {"root": str(paths.log_root)},
                "skills": {"root": str(_REPO_ROOT / "app" / "skills")},
            }
        ),
        encoding="utf-8",
    )
    return config_path


def _seed_trip(database_path: Path) -> str:
    conn = connect_sqlite(database_path)
    try:
        migrate(conn)
        trip_id = new_id("trip")
        now = utc_now_iso()
        conn.execute(
            """INSERT INTO trips
               (id, title, status, version, created_at, updated_at, archived_at)
               VALUES (?, ?, 'active', 1, ?, ?, NULL)""",
            (trip_id, "LIVE-EVAL-POLICY-STOP", now, now),
        )
        conn.commit()
        return trip_id
    finally:
        conn.close()


def _require_live_environment() -> None:
    load_dotenv()
    if os.getenv(LIVE_EVAL_GATE) != "1":
        raise EvalEnvironmentUnavailableError(code="eval_live_gate_disabled")
    if not os.getenv("OPENROUTER_API_KEY") or not os.getenv("OPENROUTER_BASE_URL"):
        raise EvalEnvironmentUnavailableError(code="eval_live_provider_config_missing")


def _environment_fingerprint() -> str:
    load_dotenv()
    model = os.getenv("MODEL", "deepseek/deepseek-v4-flash")
    base_url = os.getenv("OPENROUTER_BASE_URL", "unconfigured")
    host = urlsplit(base_url).hostname or "unconfigured"
    provider_hash = hashlib.sha256(host.encode("utf-8")).hexdigest()[:12]
    return f"real-llm:{model}:provider-{provider_hash}"


def _raise_provider_unavailable(log_root: Path) -> None:
    codes: set[str] = set()
    for path in sorted(log_root.rglob("llm.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            code = row.get("error_code")
            if row.get("status") == "failed" and code in _PROVIDER_FAILURE_CODES:
                codes.add(str(code))
    if codes:
        raise EvalEnvironmentUnavailableError(
            code="eval_live_provider_unavailable"
        )


def _trace_identities(log_root: Path) -> tuple[tuple[str, str, str], ...]:
    identities = []
    for path in sorted(log_root.rglob("traces.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = deserialize_record(json.loads(line))
            if isinstance(record, TraceRecord):
                identities.append((record.trace_id, record.run_id, record.turn_id))
    return tuple(identities)
