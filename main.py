"""Interactive CLI skeleton for the current LifeOps runtime."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.common.config import DEFAULT_CONFIG_PATH
from app.common.errors import AppError
from app.common.ids import new_id
from app.runtime.bootstrap import build_runtime_service
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.planning.models import PlanCommand, PlanCommandAction


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
        session_id = new_id("session")
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

    return 1 if had_error else 0


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
