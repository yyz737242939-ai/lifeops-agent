"""CLI skeleton for the current LifeOps runtime."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.common.config import DEFAULT_CONFIG_PATH
from app.common.errors import AppError
from app.runtime.bootstrap import build_runtime_service
from app.runtime.models import RuntimeRequest, RuntimeSession, RuntimeStatus


def main(argv: Sequence[str] | None = None) -> int:
    """Run one CLI request through the current runtime skeleton."""

    parser = argparse.ArgumentParser(description="Run one LifeOps runtime request.")
    parser.add_argument("user_input", nargs="*", help="User input for one runtime turn.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the runtime config JSON file.",
    )
    args = parser.parse_args(argv)

    user_input = " ".join(args.user_input).strip()
    if not user_input:
        print("user_input is required.")
        return 2

    runtime = None
    try:
        runtime = build_runtime_service(args.config)
        session = RuntimeSession()
        request = RuntimeRequest(
            user_input=user_input,
            session_id=session.session_id,
        )
        result = runtime.handle(request)
    except AppError as exc:
        print(f"error: {exc.code or exc.__class__.__name__}: {exc.message}")
        return 1
    finally:
        if runtime is not None:
            runtime.close()

    print(f"status: {result.status.value}")
    print(f"run_id: {result.run_id}")
    print(f"message: {result.message}")
    if result.intent is not None:
        print(f"intent: {result.intent.get('intent_type')}")
    if result.policy is not None:
        print(f"policy: {result.policy.get('action')}")

    return 1 if result.status == RuntimeStatus.ERROR else 0


if __name__ == "__main__":
    raise SystemExit(main())
