from __future__ import annotations

import argparse
import os
import subprocess
import sys


_SLICE_TARGETS = {
    "04a": (
        "tests.test_live_user_e2e.LiveUserE2ETest."
        "test_04a_real_memory_save_is_single_write_and_durable"
    ),
    "04b": (
        "tests.test_live_user_e2e.LiveUserE2ETest."
        "test_04b_real_profile_and_seeded_memory_restart_recall_is_read_only"
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one LIVE-04 slice with a hard wall-clock timeout."
    )
    parser.add_argument("slice", choices=tuple(_SLICE_TARGETS))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")

    target = _SLICE_TARGETS[args.slice]
    env = os.environ.copy()
    env["LIFEOPS_RUN_FULL_LIVE_E2E"] = "1"
    command = [sys.executable, "-m", "unittest", target, "-v"]
    print(
        f"LIVE-{args.slice.upper()} start: timeout={args.timeout_seconds}s "
        f"target={target}",
        flush=True,
    )
    process = subprocess.Popen(command, env=env)
    try:
        return process.wait(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        print(
            f"LIVE-{args.slice.upper()} TIMEOUT: exceeded "
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


if __name__ == "__main__":
    raise SystemExit(main())
