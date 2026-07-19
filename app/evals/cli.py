"""Independent CLI dispatch for trusted local Eval suites."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from app.evals.compiled import (
    DEFAULT_EVAL_MANIFEST_ROOT,
    FIXTURE_REFS,
    build_compiled_eval_runner,
)
from app.evals.errors import EvalManifestError
from app.evals.graders import default_grader_registry
from app.evals.live import LIVE_FIXTURE_REFS, build_live_eval_runner
from app.evals.loader import FileEvalSuiteLoader
from app.evals.renderers import EvalOutputFormat, EvalReportRenderer
from app.evals.aggregation import eval_exit_code


def run_eval_cli(
    argv: Sequence[str],
    *,
    default_manifest_root: str | Path = DEFAULT_EVAL_MANIFEST_ROOT,
) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic LifeOps evaluations.")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--case")
    parser.add_argument("--manifest-root", default=str(default_manifest_root))
    parser.add_argument("--workspace-root")
    parser.add_argument("--output")
    parser.add_argument("--keep-failed-workspaces", action="store_true")
    parser.add_argument("--keep-all-workspaces", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable explicitly-gated real-LLM Eval compositions.",
    )
    parser.add_argument(
        "--format",
        choices=tuple(item.value for item in EvalOutputFormat),
        default=EvalOutputFormat.TEXT.value,
    )
    args = parser.parse_args(list(argv))
    try:
        graders = default_grader_registry()
        suite = FileEvalSuiteLoader(
            Path(args.manifest_root),
            trusted_fixture_refs=(*FIXTURE_REFS, *LIVE_FIXTURE_REFS),
            trusted_grader_ids=graders.grader_ids,
        ).load(args.suite)
        if args.case is not None:
            selected = tuple(case for case in suite.cases if case.case_id == args.case)
            if len(selected) != 1:
                raise ValueError("Requested Eval case is not present in the suite.")
            suite = replace(suite, cases=selected)
        sink = _JsonReportSink(Path(args.output)) if args.output is not None else None
        live_cases = tuple(
            case for case in suite.cases if case.fixture_ref in LIVE_FIXTURE_REFS
        )
        if live_cases and not args.live:
            raise ValueError("Real-LLM Eval suites require the explicit --live flag.")
        if args.live and len(live_cases) != len(suite.cases):
            raise ValueError("--live accepts only registered real-LLM Eval cases.")
        builder = build_live_eval_runner if args.live else build_compiled_eval_runner
        runner = builder(
            workspace_root=(Path(args.workspace_root) if args.workspace_root else None),
            report_sink=sink,
        )
        from app.evals.runner import EvalRunOptions

        report = runner.run(
            suite,
            EvalRunOptions(
                keep_failed_workspaces=args.keep_failed_workspaces,
                keep_all_workspaces=args.keep_all_workspaces,
            ),
        )
        print(EvalReportRenderer().render(report, EvalOutputFormat(args.format)))
        return eval_exit_code(report)
    except (EvalManifestError, OSError, ValueError) as exc:
        print(f"error: {getattr(exc, 'message', str(exc))}")
        return 2


class _JsonReportSink:
    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, report) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            EvalReportRenderer().render(report, EvalOutputFormat.JSON) + "\n",
            encoding="utf-8",
        )
