from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.inspection import InspectionQuery, InspectionTarget, build_inspector_service
from app.observability.trace_index import TraceIndexBuilder


class InspectionCompositionTest(unittest.TestCase):
    def test_index_and_file_fallback_return_same_graph_with_explicit_warning(self) -> None:
        fixture = Path("tests/fixtures/traces/serial_diamond")
        canonical_before = {
            path.name: path.read_bytes()
            for path in fixture.glob("*.jsonl")
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "trace-index.sqlite3"
            TraceIndexBuilder(index_path).index_session(fixture)
            service = build_inspector_service(fixture, index_path=index_path)
            query = InspectionQuery(InspectionTarget(run_id="run_diamond"))

            indexed = service.inspect(query)
            index_path.unlink()
            fallback = service.inspect(query)

            self.assertEqual(indexed.trace_graphs[0].spans_by_id, fallback.trace_graphs[0].spans_by_id)
            self.assertNotIn("index_unavailable", indexed.runtime_reports[0].integrity_warnings)
            self.assertIn("index_unavailable", fallback.runtime_reports[0].integrity_warnings)
            self.assertIn("index_unavailable", fallback.trace_graphs[0].integrity_warnings)
            self.assertEqual(
                canonical_before,
                {path.name: path.read_bytes() for path in fixture.glob("*.jsonl")},
            )

    def test_missing_target_fails_without_scanning_an_unrelated_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = build_inspector_service(Path(tmpdir))
            with self.assertRaisesRegex(RuntimeError, "inspection target is unavailable"):
                service.inspect(InspectionQuery(InspectionTarget(trace_id="missing")))


if __name__ == "__main__":
    unittest.main()
