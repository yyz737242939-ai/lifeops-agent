from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry, optional_span
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import LifeOpsSpanKind, TraceStatus
from app.runtime_reporting.builder import RuntimeReportBuilder
from app.runtime_reporting.models import (
    EvidenceReport,
    FactProjection,
    RuntimeFactBundle,
)
from app.runtime_reporting.providers import (
    CompositeRuntimeFactProvider,
    EmptyRuntimeFactProvider,
)


class RuntimeReportingTest(unittest.TestCase):
    def test_builder_is_deterministic_and_keeps_fact_priority_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            graph = _graph(Path(tmpdir))
            feedback = FactProjection(
                "execution_feedback", "feedback_1", "failed",
                {"validation.status": "failed"},
            )
            stop_point = FactProjection(
                "execution_stop_point", "feedback_1:stop", "failed"
            )
            facts = RuntimeFactBundle(
                execution_feedback=feedback,
                stop_point=stop_point,
                evidence_reports=(
                    EvidenceReport("execution_feedback", "evidence_1", "feedback/evidence_1"),
                ),
                fact_source_warnings=("source_conflict",),
            )
            builder = RuntimeReportBuilder()

            first = builder.build(graph, facts)
            second = builder.build(graph, facts)

            self.assertEqual(first, second)
            self.assertEqual(first.execution_feedback, feedback)
            self.assertEqual(first.stop_point, stop_point)
            self.assertIn("source_conflict", first.integrity_warnings)
            self.assertEqual(len(first.executor_invocations), 1)
            self.assertEqual(len(first.tool_attempts), 1)

    def test_empty_and_composite_fact_providers_use_typed_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            graph = _graph(Path(tmpdir))

            class Source:
                def load(self, trace):
                    return RuntimeFactBundle(
                        run_record=FactProjection("run_record", "run_1", "ok")
                    )

            self.assertEqual(EmptyRuntimeFactProvider().load(graph), RuntimeFactBundle())
            bundle = CompositeRuntimeFactProvider((Source(),)).load(graph)
            self.assertEqual(bundle.run_record.source_id, "run_1")
            with self.assertRaises(ValueError):
                CompositeRuntimeFactProvider((Source(), Source())).load(graph)

    def test_runtime_reporting_dependency_direction_is_read_only(self) -> None:
        forbidden = (
            "app.planning", "app.executor", "app.tools", "app.recovery",
            "app.domains", "app.runtime", "app.inspection", "app.evals",
            "langgraph", "openai", "sqlite3",
        )
        violations: list[str] = []
        for path in sorted(Path("app/runtime_reporting").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                violations.extend(
                    name
                    for name in names
                    if any(name == item or name.startswith(f"{item}.") for item in forbidden)
                )
        self.assertEqual(violations, [])


def _graph(root: Path):
    logs = SessionLogWriter.create(root, session_id="session_1")
    telemetry = RequestTelemetry(
        run_id="run_1", session_id="session_1", turn_id="turn_1",
        legacy_sink=OptionalLogAppender(None), exporter=logs.trace_exporter,
    )
    trace_id = telemetry.trace_context.trace_id
    with optional_span(
        telemetry, name="executor.invoke", kind=LifeOpsSpanKind.EXECUTOR
    ):
        with optional_span(
            telemetry, name="tool.fixture", kind=LifeOpsSpanKind.TOOL,
            attributes={"lifeops.tool.outcome": "failed"},
        ):
            pass
    telemetry.finish(status=TraceStatus.OK)
    return TraceReader(FileTraceStore(root)).get_trace(trace_id)


if __name__ == "__main__":
    unittest.main()
