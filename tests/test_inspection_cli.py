from __future__ import annotations

import unittest
from unittest.mock import patch

from app.inspection import InspectionView
from app.inspection import cli


class InspectionCliTest(unittest.TestCase):
    def test_structured_cli_builds_read_only_query_and_json_output(self) -> None:
        service = _Service()
        renderer = _Renderer()
        with (
            patch.object(cli, "build_inspector_service", return_value=service) as build,
            patch.object(cli, "InspectionRenderer", return_value=renderer),
            patch("builtins.print") as output,
        ):
            exit_code = cli.run_inspector_cli(
                [
                    "--run-id", "run_1",
                    "--session-id", "session_1",
                    "--view", "summary,tree",
                    "--format", "json",
                    "--log-root", "logs/test",
                ]
            )

        self.assertEqual(exit_code, 0)
        build.assert_called_once_with(
            "logs/test", index_path=None, diagnostic_registry=None
        )
        query = service.queries[0]
        self.assertEqual(query.target.run_id, "run_1")
        self.assertEqual(query.target.session_id, "session_1")
        self.assertEqual(query.views, (InspectionView.SUMMARY, InspectionView.TREE))
        self.assertEqual(renderer.calls[0][1].value, "json")
        output.assert_called_once_with("rendered")

    def test_invalid_sensitive_view_fails_before_service_construction(self) -> None:
        with (
            patch.object(cli, "build_inspector_service") as build,
            patch("builtins.print") as output,
        ):
            exit_code = cli.run_inspector_cli(
                ["--trace-id", "trace_1", "--include-sensitive"]
            )

        self.assertEqual(exit_code, 1)
        build.assert_not_called()
        self.assertIn("requires the details view", output.call_args.args[0])


class _Service:
    def __init__(self) -> None:
        self.queries = []

    def inspect(self, query):
        self.queries.append(query)
        return object()


class _Renderer:
    def __init__(self) -> None:
        self.calls = []

    def render(self, result, output_format):
        self.calls.append((result, output_format))
        return "rendered"


if __name__ == "__main__":
    unittest.main()
