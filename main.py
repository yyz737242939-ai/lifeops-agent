"""Interactive CLI skeleton for the current LifeOps runtime."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.common.config import DEFAULT_CONFIG_PATH
from app.common.errors import AppError
from app.common.ids import new_id
from app.runtime.bootstrap import build_runtime_service
from app.runtime.confirmation import CliActionConfirmationProvider
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.planning.models import PlanCommand, PlanCommandAction
from app.recovery.runtime import build_recovery_runtime
from app.inspection.cli import run_inspector_cli
from app.evals.cli import run_eval_cli


def main(argv: Sequence[str] | None = None) -> int:
    """Run interactive CLI requests through the current runtime skeleton."""

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv and raw_argv[0].lower() == "inspect":
        return run_inspector_cli(raw_argv[1:])
    if raw_argv and raw_argv[0].lower() == "eval":
        return run_eval_cli(raw_argv[1:])

    parser = argparse.ArgumentParser(description="Run the LifeOps runtime CLI.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the runtime config JSON file.",
    )
    parser.add_argument(
        "--session-id",
        help="Reuse an existing session for explicit read-only Recovery.",
    )
    args = parser.parse_args(raw_argv)

    runtime = None
    recovery_runtime = None
    had_error = False
    try:
        session_id = args.session_id or new_id("session")
        current_plan: dict[str, object] | None = None

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
                recovery_command = _parse_recovery_command(user_input)
                if recovery_command is not _NOT_RECOVERY:
                    if recovery_runtime is None:
                        recovery_runtime = build_recovery_runtime(args.config)
                    recovery_result = recovery_runtime.explain(
                        session_id,
                        recovery_command,
                    )
                    print(recovery_result.explanation)
                    continue
                if runtime is None:
                    runtime = build_runtime_service(
                        args.config,
                        confirmation_provider=CliActionConfirmationProvider(),
                    )
                command = _parse_plan_command(user_input, session_id, current_plan)
                if command is None:
                    request = RuntimeRequest(
                        user_input=user_input,
                        session_id=session_id,
                    )
                    result = runtime.handle(request)
                else:
                    request = RuntimeRequest(
                        user_input=str(current_plan["goal"]),
                        session_id=session_id,
                    )
                    result = runtime.handle_plan_command(command, request)
            except (AppError, ValueError) as exc:
                had_error = True
                print(f"error: {getattr(exc, 'message', str(exc))}")
                continue

            print(result.message)
            current_plan = _updated_current_plan(current_plan, result)
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
        if recovery_runtime is not None:
            recovery_runtime.close()

    return 1 if had_error else 0


_NOT_RECOVERY = object()


def _parse_recovery_command(user_input: str) -> object | str | None:
    """Return source run id, None for latest, or a private non-command sentinel."""

    parts = user_input.split()
    if not parts or parts[0].lower() not in {"recover", "recover-last"}:
        return _NOT_RECOVERY
    if parts[0].lower() == "recover-last":
        if len(parts) != 1:
            raise ValueError("Usage: recover-last")
        return None
    if len(parts) != 2:
        raise ValueError("Usage: recover <run_id>")
    return parts[1]


def _parse_plan_command(
    user_input: str,
    session_id: str,
    current_plan: dict[str, object] | None,
) -> PlanCommand | None:
    """Translate explicit CLI syntax into the structured runtime contract."""

    parts = user_input.split(maxsplit=1)
    action_text = parts[0].lower()
    if action_text not in {"confirm-plan", "cancel-plan", "modify-plan"}:
        return None
    if current_plan is None:
        raise ValueError("No current plan preview is available.")
    action = {
        "confirm-plan": PlanCommandAction.CONFIRM,
        "cancel-plan": PlanCommandAction.CANCEL,
        "modify-plan": PlanCommandAction.MODIFY,
    }[action_text]
    feedback = parts[1].strip() if len(parts) == 2 else None
    return PlanCommand(
        command_id=new_id("plan_command"),
        plan_id=str(current_plan["plan_id"]),
        session_id=session_id,
        revision=int(current_plan["revision"]),
        action=action,
        feedback=feedback,
    )


def _updated_current_plan(
    current_plan: dict[str, object] | None, result: RuntimeResult
) -> dict[str, object] | None:
    tool_result = result.tool_result
    if tool_result is None:
        return current_plan
    if tool_result.get("type") == "plan_preview":
        return tool_result
    if tool_result.get("type") == "plan_result" and tool_result.get(
        "plan_status"
    ) in {"completed", "stopped", "failed", "cancelled"}:
        return None
    return current_plan


if __name__ == "__main__":
    raise SystemExit(main())
