from __future__ import annotations

import json
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from app.evals import CaseStatus, FileEvalSuiteLoader, default_grader_registry
from app.evals.cli import run_eval_cli
from app.evals.compiled import FIXTURE_REFS, build_compiled_eval_runner


class CompiledEvalDevelopmentTest(unittest.TestCase):
    def test_composition_never_reads_manifest_input_or_expectations(self) -> None:
        tree = ast.parse(Path("app/evals/compiled.py").read_text(encoding="utf-8"))
        leaked = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "case"
            and node.attr in {"input", "expectations"}
        ]
        self.assertEqual(leaked, [])

    def test_manifests_define_ten_runtime_cases_and_one_regression(self) -> None:
        loader = _loader()
        runtime = loader.load("runtime_core")
        regression = loader.load("regression")

        self.assertEqual(len(runtime.cases), 10)
        self.assertEqual(len(regression.cases), 1)
        self.assertEqual(
            {case.fixture_ref for case in (*runtime.cases, *regression.cases)},
            set(FIXTURE_REFS),
        )
        self.assertEqual(
            regression.cases[0].regression_ref,
            "recovery-false-success-validation-v1",
        )

    def test_all_compiled_development_cases_run_through_the_harness(self) -> None:
        loader = _loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = build_compiled_eval_runner(workspace_root=Path(tmpdir))
            runtime = runner.run(loader.load("runtime_core"))
            regression = runner.run(loader.load("regression"))

        self.assertTrue(
            all(case.status is CaseStatus.PASSED for case in runtime.case_results),
            [(case.case_id, case.status.value) for case in runtime.case_results],
        )
        self.assertEqual(regression.case_results[0].status, CaseStatus.PASSED)
        self.assertEqual(
            next(
                grade
                for grade in regression.case_results[0].grade_results
                if grade.grader_id == "final-answer-grounding"
            ).reason_code,
            "final-answer-grounding_passed",
        )

    def test_eval_cli_filters_case_and_writes_explicit_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch("builtins.print"):
            root = Path(tmpdir)
            output = root / "reports" / "regression.json"
            exit_code = run_eval_cli(
                [
                    "--suite", "regression",
                    "--case", "regression-false-success",
                    "--format", "json",
                    "--workspace-root", str(root / "workspaces"),
                    "--output", str(output),
                ]
            )

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["run"]["suite_id"], "regression")
        self.assertEqual(len(payload["cases"]), 1)

    def test_main_dispatches_eval_without_building_interactive_runtime(self) -> None:
        with patch.object(main, "run_eval_cli", return_value=7) as dispatch:
            exit_code = main.main(["eval", "--suite", "runtime_core"])

        self.assertEqual(exit_code, 7)
        dispatch.assert_called_once_with(["--suite", "runtime_core"])


def _loader() -> FileEvalSuiteLoader:
    return FileEvalSuiteLoader(
        Path("evals/manifests"),
        trusted_fixture_refs=FIXTURE_REFS,
        trusted_grader_ids=default_grader_registry().grader_ids,
    )


if __name__ == "__main__":
    unittest.main()
