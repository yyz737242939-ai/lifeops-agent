from __future__ import annotations

import ast
import dataclasses
import json
import unittest
from pathlib import Path

from app.observability.trace_models import (
    AnnotationRecord,
    ArtifactReference,
    SpanEventRecord,
    SpanLinkRecord,
    SpanRecord,
    TraceRecord,
)
from app.observability.trace_vocabulary import (
    TRACE_SCHEMA_VERSION,
    AnnotationKind,
    AnnotationProducer,
    AnnotationSeverity,
    AnnotationStatus,
    ArtifactSensitivity,
    LifeOpsSpanKind,
    SpanLinkType,
    TraceSource,
    TraceStatus,
)

NOW = "2026-07-17T01:02:03+00:00"


class TraceModelsTest(unittest.TestCase):
    def test_constructs_all_v1_records(self) -> None:
        trace = TraceRecord(
            trace_id="trace_1", session_id="session_1", turn_id="turn_1",
            run_id="run_1", root_span_id="span_root", source=TraceSource.INTERACTIVE,
            started_at=NOW, status=TraceStatus.OK,
            resource_attributes={"service.name": "lifeops", "worker.count": 1},
        )
        span = SpanRecord(
            trace_id=trace.trace_id, span_id="span_child", parent_span_id=trace.root_span_id,
            name="intent.classify", lifeops_span_kind=LifeOpsSpanKind.INTENT,
            started_at=NOW, status=TraceStatus.OK, attributes={"lifeops.runtime.run_id": "run_1"},
        )
        event = SpanEventRecord(
            event_id="event_1", trace_id=trace.trace_id, span_id=span.span_id,
            sequence=1, name="intent.classified", timestamp=NOW, level="info",
            attributes={"intent.type": "chat"},
        )
        link = SpanLinkRecord(
            link_id="link_1", source_trace_id=trace.trace_id, source_span_id=span.span_id,
            target_trace_id="trace_preview", target_span_id="span_preview",
            link_type=SpanLinkType.PLAN_CONTINUATION,
        )
        artifact = ArtifactReference(
            artifact_id="artifact_1", trace_id=trace.trace_id, span_id=span.span_id,
            artifact_type="execution_feedback", storage_kind="session_file",
            safe_reference="artifacts/artifact_1.json", content_hash="a" * 64,
            sensitivity=ArtifactSensitivity.SENSITIVE, created_at=NOW,
        )
        annotation = AnnotationRecord(
            annotation_id="annotation_1", target_trace_id=trace.trace_id,
            target_span_id=span.span_id, annotation_kind=AnnotationKind.EVALUATION,
            producer=AnnotationProducer.DETERMINISTIC_RULE, producer_version="1",
            source_fingerprint="fixture-v1", evaluator_id="trace_contract",
            eval_run_id="eval_run_1", eval_suite_id="suite_1", eval_case_id="case_1",
            status=AnnotationStatus.PASSED, severity=AnnotationSeverity.INFO,
            score=1.0, reason_code="contract_valid", created_at=NOW,
        )

        self.assertEqual(trace.schema_version, TRACE_SCHEMA_VERSION)
        self.assertEqual(span.attributes, {"lifeops.runtime.run_id": "run_1"})
        self.assertEqual(event.sequence, 1)
        self.assertEqual(link.link_type, SpanLinkType.PLAN_CONTINUATION)
        self.assertEqual(artifact.content_hash, "a" * 64)
        self.assertEqual(annotation.eval_case_id, "case_1")

    def test_rejects_empty_ids_invalid_timestamps_enums_and_sequence(self) -> None:
        base = dict(
            trace_id="trace_1", session_id="session_1", turn_id="turn_1", run_id="run_1",
            root_span_id="span_1", source=TraceSource.INTERACTIVE, started_at=NOW,
        )
        for field in ("trace_id", "session_id", "turn_id", "run_id", "root_span_id"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                TraceRecord(**(base | {field: ""}))
        with self.assertRaises(ValueError):
            TraceRecord(**(base | {"started_at": "not-a-time"}))
        with self.assertRaises(ValueError):
            TraceRecord(**(base | {"started_at": "2026-07-17T01:02:03"}))
        with self.assertRaises(ValueError):
            TraceRecord(**(base | {"source": "interactive"}))
        with self.assertRaises(ValueError):
            SpanEventRecord(
                event_id="event_1", trace_id="trace_1", span_id="span_1", sequence=0,
                name="runtime.started", timestamp=NOW, level="info",
            )

    def test_span_parent_and_link_identity_constraints(self) -> None:
        with self.assertRaises(ValueError):
            SpanRecord(
                trace_id="trace_1", span_id="span_1", parent_span_id="span_1",
                name="runtime", lifeops_span_kind=LifeOpsSpanKind.RUNTIME, started_at=NOW,
            )
        with self.assertRaises(ValueError):
            SpanLinkRecord(
                link_id="link_1", source_trace_id="trace_1", source_span_id="span_1",
                target_trace_id="trace_1", target_span_id="span_1",
                link_type=SpanLinkType.DEPENDS_ON,
            )

    def test_annotation_requires_valid_eval_lineage_and_enum_values(self) -> None:
        base = dict(
            annotation_id="annotation_1", target_trace_id="trace_1",
            annotation_kind=AnnotationKind.EVALUATION,
            producer=AnnotationProducer.DETERMINISTIC_RULE,
            evaluator_id="grader", status=AnnotationStatus.PASSED, created_at=NOW,
        )
        with self.assertRaises(ValueError):
            AnnotationRecord(**base)
        with self.assertRaises(ValueError):
            AnnotationRecord(**(base | {"eval_run_id": "eval_1", "eval_suite_id": "suite_1"}))
        with self.assertRaises(ValueError):
            AnnotationRecord(**(base | {
                "eval_run_id": "eval_1", "eval_suite_id": "suite_1", "eval_case_id": "case_1",
                "producer": "deterministic_rule",
            }))
        with self.assertRaises(ValueError):
            AnnotationRecord(**(base | {
                "eval_run_id": "eval_1", "eval_suite_id": "suite_1", "eval_case_id": "case_1",
                "severity": "info",
            }))

    def test_artifact_sensitivity_reference_and_hash_validation(self) -> None:
        base = dict(
            artifact_id="artifact_1", trace_id="trace_1", artifact_type="execution_feedback",
            storage_kind="session_file", safe_reference="artifacts/artifact_1.json",
            sensitivity=ArtifactSensitivity.INTERNAL, created_at=NOW,
        )
        with self.assertRaises(ValueError):
            ArtifactReference(**(base | {"safe_reference": ""}))
        with self.assertRaises(ValueError):
            ArtifactReference(**(base | {"content_hash": "not-a-hash"}))
        with self.assertRaises(ValueError):
            ArtifactReference(**(base | {"sensitivity": "internal"}))

    def test_metadata_is_safe_json_serializable_and_deeply_immutable(self) -> None:
        source = {"service.name": "lifeops", "retryable": False, "tags": ["a", "b"]}
        trace = TraceRecord(
            trace_id="trace_1", session_id="session_1", turn_id="turn_1", run_id="run_1",
            root_span_id="span_1", source=TraceSource.INTERACTIVE, started_at=NOW,
            resource_attributes=source,
        )
        source["service.name"] = "changed"
        self.assertEqual(trace.resource_attributes["service.name"], "lifeops")
        self.assertEqual(json.loads(json.dumps(trace.resource_attributes))["tags"], ["a", "b"])
        with self.assertRaises(TypeError):
            trace.resource_attributes["service.name"] = "changed"  # type: ignore[index]
        with self.assertRaises((dataclasses.FrozenInstanceError, AttributeError)):
            trace.trace_id = "changed"  # type: ignore[misc]
        for unsafe in ("raw_prompt", "user_input", "tool.arguments", "private_reasoning"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                TraceRecord(
                    trace_id="trace_1", session_id="session_1", turn_id="turn_1", run_id="run_1",
                    root_span_id="span_1", source=TraceSource.INTERACTIVE, started_at=NOW,
                    resource_attributes={unsafe: "fixture-redacted"},
                )
        safe_usage = SpanRecord(
            trace_id="trace_1",
            span_id="span_usage",
            name="llm.fixture",
            lifeops_span_kind=LifeOpsSpanKind.LLM,
            started_at=NOW,
            attributes={"llm.usage.output_tokens": 3},
        )
        self.assertEqual(safe_usage.attributes["llm.usage.output_tokens"], 3)
        with self.assertRaises(ValueError):
            SpanRecord(
                trace_id="trace_1",
                span_id="span_unsafe_output",
                name="tool.fixture",
                lifeops_span_kind=LifeOpsSpanKind.TOOL,
                started_at=NOW,
                attributes={"tool.output": "fixture-redacted"},
            )
        with self.assertRaises(ValueError):
            SpanRecord(
                trace_id="trace_1", span_id="span_1", name="runtime",
                lifeops_span_kind=LifeOpsSpanKind.RUNTIME, started_at=NOW,
                attributes={"nested": {"not": "metadata"}},
            )

    def test_schema_version_contract_is_exactly_v1(self) -> None:
        self.assertEqual(TRACE_SCHEMA_VERSION, 1)
        with self.assertRaises(ValueError):
            TraceRecord(
                trace_id="trace_1", session_id="session_1", turn_id="turn_1", run_id="run_1",
                root_span_id="span_1", source=TraceSource.INTERACTIVE, started_at=NOW,
                schema_version=2,
            )
        self.assertEqual(
            [field.name for field in dataclasses.fields(TraceRecord)],
            [
                "trace_id", "session_id", "turn_id", "run_id", "root_span_id", "source",
                "started_at", "ended_at", "status", "error_code", "resource_attributes",
                "schema_version",
            ],
        )

    def test_observability_trace_models_do_not_import_higher_layers(self) -> None:
        forbidden = (
            "app.orchestration", "app.runtime", "app.planning", "app.executor", "app.tools",
            "app.recovery", "app.domains", "app.runtime_reporting", "langgraph", "openai",
            "sqlite3",
        )
        violations: list[str] = []
        for filename in ("trace_models.py", "trace_vocabulary.py"):
            path = Path("app/observability") / filename
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                violations.extend(name for name in names if name.startswith(forbidden))
        self.assertEqual(violations, [])

    def test_test_fixtures_do_not_contain_forbidden_sensitive_fields(self) -> None:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        forbidden_fields = {
            "prompt", "user_input", "arguments", "output", "confirmation", "credentials",
        }
        fixture_keywords = {
            keyword.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        self.assertTrue(fixture_keywords.isdisjoint(forbidden_fields))


if __name__ == "__main__":
    unittest.main()
