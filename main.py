"""Interactive CLI skeleton for the current LifeOps runtime."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.common.config import DEFAULT_CONFIG_PATH
from app.common.errors import AppError
from app.runtime.bootstrap import build_runtime_service
from app.runtime.models import RuntimeRequest, RuntimeSession, RuntimeStatus


def main(argv: Sequence[str] | None = None) -> int:
    """Run interactive CLI requests through the current runtime skeleton."""

    parser = argparse.ArgumentParser(description="Run the LifeOps runtime CLI.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the runtime config JSON file.",
    )
    args = parser.parse_args(argv)

    runtime = None
    had_error = False
    try:
        runtime = build_runtime_service(args.config)
        session = RuntimeSession()

        print("LifeOps CLI. Type exit or quit to stop.")
        while True:
            try:
                user_input = input("> ").strip()
            except EOFError:
                print()
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break

            try:
                request = RuntimeRequest(
                    user_input=user_input,
                    session_id=session.session_id,
                )
                result = runtime.handle(request)
            except AppError as exc:
                had_error = True
                print(f"error: {exc.message}")
                continue

            print(result.message)
            if result.status == RuntimeStatus.ERROR:
                had_error = True
    except AppError as exc:
        print(f"error: {exc.message}")
        return 1
    except KeyboardInterrupt:
        print()
    finally:
        if runtime is not None:
            runtime.close()

    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
