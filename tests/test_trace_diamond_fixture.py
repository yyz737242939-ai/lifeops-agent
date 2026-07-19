from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.observability.trace_index import TraceIndexBuilder
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import LifeOpsSpanKind, SpanLinkType
from app.runtime_reporting.builder import RuntimeReportBuilder
from app.runtime_reporting.providers import EmptyRuntimeFactProvider


class SerialDiamondTraceFixtureTest(unittest.TestCase):
    def test_shared_contract_expresses_serial_dependency_and_partial_outcomes(self) -> None:
        fixture = Path("tests/fixtures/traces/serial_diamond")
        graph = TraceReader(FileTraceStore(fixture)).get_trace("trace_diamond")
        scheduler = graph.spans_by_id["span_scheduler"]
        nodes = {
            span.attributes["lifeops.workflow.node.id"]: span
            for span in graph.children_by_parent[scheduler.span_id]
            if "lifeops.workflow.node.id" in span.attributes
        }

        self.assertEqual(tuple(nodes), ("A", "B", "C", "D"))
        self.assertTrue(
            all(span.parent_span_id == scheduler.span_id for span in nodes.values())
        )
        self.assertEqual(
            {
                key: value.attributes["lifeops.workflow.node.outcome"]
                for key, value in nodes.items()
            },
            {"A": "succeeded", "B": "succeeded", "C": "failed", "D": "blocked"},
        )
        dependencies = {
            (link.source_span_id, link.target_span_id)
            for link in graph.links
            if link.link_type is SpanLinkType.DEPENDS_ON
        }
        self.assertEqual(
            dependencies,
            {
                ("span_b", "span_a"), ("span_c", "span_a"),
                ("span_d", "span_b"), ("span_d", "span_c"),
            },
        )
        self.assertEqual(graph.artifacts[0].span_id, nodes["B"].span_id)
        self.assertEqual(graph.artifacts[0].safe_reference, "fixtures/evidence/b")
        self.assertFalse(
            any(
                span.lifeops_span_kind is LifeOpsSpanKind.TOOL
                and span.parent_span_id == nodes["D"].span_id
                for span in graph.spans_by_id.values()
            )
        )

    def test_index_reader_and_shared_report_consume_same_fixture(self) -> None:
        fixture = Path("tests/fixtures/traces/serial_diamond")
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index.sqlite3"
            TraceIndexBuilder(index_path).index_session(fixture)
            reader = TraceReader(FileTraceStore(fixture, index_path=index_path))
            graph = reader.find_by_run("run_diamond")
            facts = EmptyRuntimeFactProvider().load(graph)
            report = RuntimeReportBuilder().build(graph, facts)

            self.assertEqual(report.identity.trace_id, "trace_diamond")
            self.assertEqual(len(report.executor_invocations), 4)
            self.assertEqual(len(report.evidence), 1)
            self.assertEqual(report.integrity_warnings, ())


if __name__ == "__main__":
    unittest.main()
