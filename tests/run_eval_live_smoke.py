from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


_CASES = (
    "live-direct-read",
    "live-planning-confirm",
    "live-recovery-explain",
    "live-policy-stop",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one real-LLM Eval case with a hard wall-clock timeout."
    )
    parser.add_argument("case", choices=_CASES)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--output-root", default=".tmp/eval-live-reports")
    parser.add_argument("--workspace-root", default=".tmp/eval-live-workspaces")
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")

    output = Path(args.output_root).resolve() / f"{args.case}.json"
    workspace_root = Path(args.workspace_root).resolve()
    env = os.environ.copy()
    env["LIFEOPS_RUN_EVAL_REAL_LLM_SMOKE"] = "1"
    command = [
        sys.executable,
        "main.py",
        "eval",
        "--live",
        "--suite",
        "real_llm_smoke",
        "--case",
        args.case,
        "--output",
        str(output),
        "--workspace-root",
        str(workspace_root),
        "--keep-failed-workspaces",
        "--format",
        "text",
    ]
    print(
        f"REAL-LLM EVAL start: case={args.case} timeout={args.timeout_seconds}s "
        f"report={output}",
        flush=True,
    )
    process = subprocess.Popen(command, env=env)
    try:
        code = process.wait(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        print(
            f"REAL-LLM EVAL TIMEOUT: case={args.case} exceeded "
            f"{args.timeout_seconds}s; terminating pid={process.pid}",
            file=sys.stderr,
            flush=True,
        )
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 124
    print(f"REAL-LLM EVAL complete: case={args.case} exit={code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
