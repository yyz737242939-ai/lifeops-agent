from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from app.inspection import (
    InspectionOutputFormat,
    InspectionRenderer,
    InspectionResult,
    InspectionTarget,
    InspectionView,
)
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.runtime_reporting import EmptyRuntimeFactProvider, RuntimeReportBuilder


class InspectionRendererTest(unittest.TestCase):
    def test_summary_tree_timeline_and_details_are_deterministic(self) -> None:
        result = _result(
            (
                InspectionView.SUMMARY,
                InspectionView.TREE,
                InspectionView.TIMELINE,
                InspectionView.DETAILS,
            )
        )
        renderer = InspectionRenderer()

        first = renderer.render(result, InspectionOutputFormat.JSON)
        second = renderer.render(result, InspectionOutputFormat.JSON)
        payload = json.loads(first)

        self.assertEqual(first, second)
        self.assertEqual(payload["sections"]["summary"][0]["trace_id"], "trace_diamond")
        self.assertEqual(payload["sections"]["tree"][0][0]["kind"], "RUNTIME")
        self.assertEqual(
            [row["identity"] for row in payload["sections"]["timeline"][0]][0],
            "span_root",
        )
        details = payload["sections"]["details"][0]
        self.assertTrue(any(row["span_id"] == "span_c" for row in details))

    def test_details_can_select_one_span_and_text_contains_same_safe_identity(self) -> None:
        result = _result((InspectionView.DETAILS,), span_id="span_c")
        renderer = InspectionRenderer()
        payload = json.loads(renderer.render(result, InspectionOutputFormat.JSON))
        text = renderer.render(result)

        self.assertEqual(
            [row["span_id"] for row in payload["sections"]["details"][0]],
            ["span_c"],
        )
        self.assertIn("[details]", text)
        self.assertIn('"span_id": "span_c"', text)
        self.assertNotIn("raw prompt", text.lower())

    def test_graph_uses_dependency_links_instead_of_parent_containment(self) -> None:
        result = _result((InspectionView.TREE, InspectionView.GRAPH))
        payload = json.loads(
            InspectionRenderer().render(result, InspectionOutputFormat.JSON)
        )
        nodes = {
            row["node_id"]: row for row in payload["sections"]["graph"][0]
        }

        self.assertEqual(nodes["A"]["dependencies"], [])
        self.assertEqual(nodes["B"]["dependencies"], ["span_a"])
        self.assertEqual(nodes["C"]["outcome"], "failed")
        self.assertEqual(nodes["D"]["blocked_by"], ["span_c"])
        self.assertEqual(nodes["B"]["evidence"], ["artifact_b_evidence"])
        tree_nodes = payload["sections"]["tree"][0]
        self.assertTrue(
            all(
                row["depth"] == 2
                for row in tree_nodes
                if row["span_id"] in {"span_a", "span_b", "span_c", "span_d"}
            )
        )

    def test_evidence_view_is_metadata_only_even_when_sensitive_is_requested(self) -> None:
        result = _result(
            (InspectionView.DETAILS, InspectionView.EVIDENCE),
            include_sensitive=True,
        )
        rendered = InspectionRenderer().render(result, InspectionOutputFormat.JSON)
        payload = json.loads(rendered)
        evidence = payload["sections"]["evidence"][0]

        self.assertEqual(
            evidence["artifact_references"][0]["artifact_id"],
            "artifact_b_evidence",
        )
        self.assertEqual(
            evidence["artifact_references"][0]["availability"],
            "metadata_only",
        )
        self.assertFalse(evidence["artifact_references"][0]["content_included"])
        self.assertEqual(evidence["sensitive_access"], "not_configured")
        self.assertNotIn("content", evidence["artifact_references"][0])

    def test_privacy_integrity_and_annotations_views_are_safe(self) -> None:
        result = _result(
            (
                InspectionView.DETAILS,
                InspectionView.INTEGRITY,
                InspectionView.ANNOTATIONS,
            ),
            span_id="span_c",
        )
        graph = result.trace_graphs[0]
        sensitive_span = replace(
            graph.spans_by_id["span_c"],
            attributes={"memory.content": "SECRET-MARKER", "safe.count": 1},
        )
        spans = dict(graph.spans_by_id)
        spans["span_c"] = sensitive_span
        result = replace(result, trace_graphs=(replace(graph, spans_by_id=spans),))

        rendered = InspectionRenderer().render(result, InspectionOutputFormat.JSON)
        payload = json.loads(rendered)

        self.assertNotIn("SECRET-MARKER", rendered)
        self.assertEqual(
            payload["sections"]["details"][0][0]["attributes"],
            {"safe.count": 1},
        )
        self.assertIn("status", payload["sections"]["integrity"][0])
        annotations = payload["sections"]["annotations"][0]
        self.assertIn("persisted_evaluation", annotations)


def _result(
    views: tuple[InspectionView, ...],
    *,
    span_id: str | None = None,
    include_sensitive: bool = False,
) -> InspectionResult:
    graph = TraceReader(
        FileTraceStore(Path("tests/fixtures/traces/serial_diamond"))
    ).get_trace("trace_diamond")
    report = RuntimeReportBuilder().build(graph, EmptyRuntimeFactProvider().load(graph))
    return InspectionResult(
        target=InspectionTarget(trace_id="trace_diamond"),
        views=views,
        trace_graphs=(graph,),
        runtime_reports=(report,),
        span_id=span_id,
        include_sensitive=include_sensitive,
    )


if __name__ == "__main__":
    unittest.main()
