from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

from app.evals import (
    EvalStateProbeError,
    EvalStateProbeErrorCode,
    EvalStateProbeRegistry,
    EvalWorkspace,
    EvalWorkspaceFactory,
    EvalWorkspacePaths,
    PlanLifecycleFactSource,
    build_state_delta,
)
from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import TraceStatus
from app.planning.errors import PlanRepositoryError
from app.planning.models import (
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepStatus,
)
from app.runtime_reporting import RuntimeReportBuilder


class EvalWorkspaceTest(unittest.TestCase):
    def test_cleanup_owner_cannot_be_bound_to_an_arbitrary_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = EvalWorkspacePaths(
                root=root,
                database_path=root / "data" / "lifeops.sqlite3",
                log_root=root / "logs",
                context_root=root / "context",
                memory_root=root / "memory",
                report_root=root / "reports",
            )
            with self.assertRaises(ValueError):
                EvalWorkspace(paths)
            self.assertTrue(root.exists())

    def test_each_case_gets_private_paths_and_cleanup_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            factory = EvalWorkspaceFactory(base)
            first = factory.create("direct-final")
            second = factory.create("direct-final")

            self.assertNotEqual(first.paths.root, second.paths.root)
            for workspace in (first, second):
                self.assertEqual(
                    workspace.paths.database_path.parent,
                    workspace.paths.root / "data",
                )
                for path in (
                    workspace.paths.log_root,
                    workspace.paths.context_root,
                    workspace.paths.memory_root,
                    workspace.paths.report_root,
                ):
                    self.assertTrue(path.is_dir())
                    path.resolve().relative_to(workspace.paths.root.resolve())

            first_root = first.paths.root
            first.close()
            first.close()
            self.assertTrue(first.closed)
            self.assertFalse(first_root.exists())
            second.close()

    def test_failed_workspace_can_be_explicitly_retained(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = EvalWorkspaceFactory(Path(tmpdir)).create("failed-case")
            retained_root = workspace.paths.root
            workspace.close(keep=True)

            self.assertTrue(workspace.closed)
            self.assertTrue(workspace.retained)
            self.assertTrue(retained_root.is_dir())
            shutil.rmtree(retained_root)


class EvalStateProbeRegistryTest(unittest.TestCase):
    def test_registered_probes_capture_immutable_snapshots_and_typed_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = EvalWorkspaceFactory(Path(tmpdir)).create("state-change")
            state = {"count": 0, "items": ["a"]}
            registry = EvalStateProbeRegistry((_DictionaryProbe("task-state", state),))

            before = registry.capture(("task-state",), workspace.paths)
            state["count"] = 1
            state["items"].append("b")
            state["created"] = True
            after = registry.capture(("task-state",), workspace.paths)
            delta = build_state_delta(before, after)

            self.assertEqual(before[0].safe_values["items"], ("a",))
            self.assertEqual(
                tuple((change.key, change.before, change.after) for change in delta.changes),
                (
                    ("count", 0, 1),
                    ("created", None, True),
                    ("items", ("a",), ("a", "b")),
                ),
            )
            self.assertFalse(delta.changes[1].before_present)
            self.assertTrue(delta.changes[1].after_present)
            with self.assertRaises(TypeError):
                before[0].safe_values["count"] = 9  # type: ignore[index]
            workspace.close()

    def test_unknown_duplicate_and_failed_probes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = EvalWorkspaceFactory(Path(tmpdir)).create("probe-failure")
            registry = EvalStateProbeRegistry((_FailingProbe(),))

            with self.assertRaises(EvalStateProbeError) as unknown:
                registry.capture(("unknown-probe",), workspace.paths)
            self.assertEqual(
                unknown.exception.code,
                EvalStateProbeErrorCode.UNKNOWN_PROBE.value,
            )
            with self.assertRaises(EvalStateProbeError) as failed:
                registry.capture(("failing-probe",), workspace.paths)
            self.assertEqual(
                failed.exception.code,
                EvalStateProbeErrorCode.PROBE_FAILED.value,
            )
            self.assertNotIn("private database detail", failed.exception.message)
            with self.assertRaises(ValueError):
                registry.capture(("failing-probe", "failing-probe"), workspace.paths)
            with self.assertRaises(ValueError):
                EvalStateProbeRegistry((_FailingProbe(), _FailingProbe()))
            workspace.close()

    def test_delta_requires_the_same_probe_set_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = EvalWorkspaceFactory(Path(tmpdir)).create("probe-order")
            registry = EvalStateProbeRegistry(
                (
                    _DictionaryProbe("first-probe", {}),
                    _DictionaryProbe("second-probe", {}),
                )
            )
            before = registry.capture(("first-probe", "second-probe"), workspace.paths)
            after = registry.capture(("second-probe", "first-probe"), workspace.paths)

            with self.assertRaises(EvalStateProbeError) as raised:
                build_state_delta(before, after)
            self.assertEqual(
                raised.exception.code,
                EvalStateProbeErrorCode.SNAPSHOT_MISMATCH.value,
            )
            workspace.close()


class PlanLifecycleFactSourceTest(unittest.TestCase):
    def test_projects_repository_models_through_shared_fact_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            graph = _graph(Path(tmpdir))
            repository = _PlanRepository()
            source = PlanLifecycleFactSource(repository, "plan-1")

            facts = source.load(graph)
            report = RuntimeReportBuilder().build(graph, facts)

            self.assertEqual(repository.calls, [("session-1", "plan-1", False)])
            self.assertEqual(
                tuple(item.source_kind for item in report.plan_report),
                ("plan_run", "plan_step", "plan_step"),
            )
            self.assertEqual(
                tuple(item.status for item in report.plan_report),
                ("running", "completed", "pending"),
            )
            self.assertEqual(
                report.plan_report[2].attributes["dependency_step_ids"],
                ("step-1",),
            )

    def test_repository_failure_becomes_safe_fact_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            facts = PlanLifecycleFactSource(
                _FailingPlanRepository(), "plan-1"
            ).load(_graph(Path(tmpdir)))
            self.assertEqual(
                facts.fact_source_warnings,
                ("plan_lifecycle_unavailable",),
            )
            self.assertEqual(facts.plan_runs_and_steps, ())

    def test_eval_dependency_direction_does_not_leak_into_frozen_modules(self) -> None:
        eval_allowed = (
            "app.common",
            "app.evals",
            "app.observability",
            "app.planning",
            "app.recovery",
            "app.runtime",
            "app.runtime_reporting",
        )
        imports = _app_imports(
            Path("app/evals"), exclude=("cli.py", "compiled.py", "live.py")
        )
        self.assertEqual(
            [name for name in imports if not name.startswith(eval_allowed)],
            [],
        )
        composition_allowed = (
            *eval_allowed,
            "app.executor",
            "app.intent",
            "app.policy",
            "app.skills",
            "app.storage",
            "app.tools",
        )
        composition_imports = _app_imports(
            Path("app/evals"), include=("cli.py", "compiled.py", "live.py")
        )
        self.assertEqual(
            [
                name
                for name in composition_imports
                if not name.startswith(composition_allowed)
            ],
            [],
        )
        for frozen_root in (
            "app/executor",
            "app/intent",
            "app/policy",
            "app/runtime_reporting",
            "app/observability",
            "app/planning",
            "app/recovery",
            "app/runtime",
            "app/skills",
            "app/storage",
            "app/tools",
            "app/inspection",
        ):
            self.assertNotIn("app.evals", _app_imports(Path(frozen_root)))


class _DictionaryProbe:
    def __init__(self, probe_id: str, values: dict[str, object]) -> None:
        self.probe_id = probe_id
        self._values = values

    def read(self, workspace):
        return self._values


class _FailingProbe:
    probe_id = "failing-probe"

    def read(self, workspace):
        raise RuntimeError("private database detail")


class _PlanRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def get_plan(self, session_id, plan_id, *, recover_interrupted=False):
        self.calls.append((session_id, plan_id, recover_interrupted))
        plan = PlanRun(
            plan_id=plan_id,
            session_id=session_id,
            goal="Complete the fixture.",
            status=PlanRunStatus.RUNNING,
        )
        steps = (
            PlanStep(
                plan_id=plan_id,
                revision=1,
                step_id="step-1",
                position=1,
                objective="First",
                expected_outcome="First done",
                dependency_step_ids=(),
                status=PlanStepStatus.COMPLETED,
                safe_result_summary="done",
                evidence_refs=("evidence-1",),
            ),
            PlanStep(
                plan_id=plan_id,
                revision=1,
                step_id="step-2",
                position=2,
                objective="Second",
                expected_outcome="Second done",
                dependency_step_ids=("step-1",),
                status=PlanStepStatus.PENDING,
            ),
        )
        return plan, steps


class _FailingPlanRepository:
    def get_plan(self, session_id, plan_id, *, recover_interrupted=False):
        raise PlanRepositoryError(
            "private repository detail",
            code="plan_repository_failed",
        )


def _graph(root: Path):
    logs = SessionLogWriter.create(root, session_id="session-1")
    telemetry = RequestTelemetry(
        run_id="run-1",
        session_id="session-1",
        turn_id="turn-1",
        legacy_sink=OptionalLogAppender(None),
        exporter=logs.trace_exporter,
    )
    trace_id = telemetry.trace_context.trace_id
    telemetry.finish(status=TraceStatus.OK)
    return TraceReader(FileTraceStore(root)).get_trace(trace_id)


def _app_imports(
    root: Path,
    *,
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
) -> list[str]:
    imports: list[str] = []
    for path in sorted(root.glob("*.py")):
        if include and path.name not in include:
            continue
        if path.name in exclude:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names if alias.name.startswith("app."))
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
                imports.append(node.module)
    return imports


if __name__ == "__main__":
    unittest.main()
