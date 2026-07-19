from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.evals.aggregation import eval_exit_code
from app.evals.cli import run_eval_cli
from app.evals.compiled import DEFAULT_EVAL_MANIFEST_ROOT, FIXTURE_REFS
from app.evals.contracts import CaseStatus, FailureClassification
from app.evals.graders import default_grader_registry
from app.evals.live import LIVE_EVAL_GATE, LIVE_FIXTURE_REFS, build_live_eval_runner
from app.evals.loader import FileEvalSuiteLoader


class LiveEvalCompositionTest(unittest.TestCase):
    def test_live_suite_loads_four_registered_real_llm_cases(self) -> None:
        suite = _load_suite()

        self.assertEqual(tuple(case.fixture_ref for case in suite.cases), LIVE_FIXTURE_REFS)
        self.assertTrue(all("live" in case.tags for case in suite.cases))
        self.assertTrue(all("real-llm" in case.tags for case in suite.cases))

    def test_disabled_gate_is_environment_unavailable_without_building_runtime(self) -> None:
        suite = _load_suite()
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ", {LIVE_EVAL_GATE: "0"}, clear=False
        ):
            report = build_live_eval_runner(
                workspace_root=Path(tmpdir) / "workspaces"
            ).run(suite)

        self.assertTrue(all(item.status is CaseStatus.UNAVAILABLE for item in report.case_results))
        self.assertTrue(
            all(
                item.failure_classification
                is FailureClassification.ENVIRONMENT_UNAVAILABLE
                for item in report.case_results
            )
        )
        self.assertEqual(eval_exit_code(report), 3)

    def test_cli_requires_explicit_live_flag_and_writes_unavailable_report(self) -> None:
        self.assertEqual(run_eval_cli(["--suite", "real_llm_smoke"]), 2)
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ", {LIVE_EVAL_GATE: "0"}, clear=False
        ):
            output = Path(tmpdir) / "report.json"
            code = run_eval_cli(
                [
                    "--live",
                    "--suite",
                    "real_llm_smoke",
                    "--case",
                    "live-direct-read",
                    "--output",
                    str(output),
                    "--format",
                    "json",
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(code, 3)
        self.assertEqual(payload["run"]["status"], "unavailable")
        self.assertEqual(
            payload["cases"][0]["failure_classification"],
            "environment_unavailable",
        )


def _load_suite():
    graders = default_grader_registry()
    return FileEvalSuiteLoader(
        DEFAULT_EVAL_MANIFEST_ROOT,
        trusted_fixture_refs=(*FIXTURE_REFS, *LIVE_FIXTURE_REFS),
        trusted_grader_ids=graders.grader_ids,
    ).load("real_llm_smoke")


if __name__ == "__main__":
    unittest.main()
