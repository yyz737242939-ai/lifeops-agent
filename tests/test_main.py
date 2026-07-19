from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main as cli
from app.common.errors import AppError
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus


class MainCliTest(unittest.TestCase):
    def test_inspect_command_uses_independent_dispatch_only(self) -> None:
        with (
            patch.object(cli, "run_inspector_cli", return_value=0) as inspect,
            patch.object(cli, "build_runtime_service") as build_normal,
            patch.object(cli, "build_recovery_runtime") as build_recovery,
        ):
            exit_code = cli.main(
                ["inspect", "--run-id", "run_1", "--view", "summary,tree"]
            )

        self.assertEqual(exit_code, 0)
        inspect.assert_called_once_with(
            ["--run-id", "run_1", "--view", "summary,tree"]
        )
        build_normal.assert_not_called()
        build_recovery.assert_not_called()

    def test_reuses_one_session_id_across_turns_and_closes_runtime(self) -> None:
        runtime = _RecordingRuntime()

        with (
            patch.object(cli, "build_runtime_service", return_value=runtime) as build,
            patch.object(cli, "new_id", return_value="session_cli"),
            patch("builtins.input", side_effect=["first", "", "second", "exit"]),
            patch("builtins.print"),
        ):
            exit_code = cli.main(["--config", "config/test.json"])

        self.assertEqual(exit_code, 0)
        build.assert_called_once()
        self.assertEqual(build.call_args.args, ("config/test.json",))
        self.assertIsInstance(
            build.call_args.kwargs["confirmation_provider"],
            cli.CliActionConfirmationProvider,
        )
        self.assertTrue(runtime.closed)
        self.assertEqual(
            [request.user_input for request in runtime.requests],
            ["first", "second"],
        )
        self.assertEqual(
            {request.session_id for request in runtime.requests},
            {"session_cli"},
        )
        self.assertEqual(len({request.turn_id for request in runtime.requests}), 2)
        self.assertEqual(len({request.run_id for request in runtime.requests}), 2)

    def test_expected_turn_error_sets_nonzero_exit_and_still_closes_runtime(self) -> None:
        runtime = _RecordingRuntime(error=AppError("turn failed"))

        with (
            patch.object(cli, "build_runtime_service", return_value=runtime),
            patch.object(cli, "new_id", return_value="session_cli"),
            patch("builtins.input", side_effect=["fail", "exit"]),
            patch("builtins.print") as output,
        ):
            exit_code = cli.main([])

        self.assertEqual(exit_code, 1)
        self.assertTrue(runtime.closed)
        output.assert_any_call("error: turn failed")

    def test_terminal_plan_result_clears_current_preview(self) -> None:
        current = {"type": "plan_preview", "plan_id": "plan_1", "revision": 1}
        result = RuntimeResult(
            "run_1",
            "session_1",
            RuntimeStatus.OK,
            "Plan cancelled.",
            tool_result={
                "type": "plan_result",
                "plan_id": "plan_1",
                "revision": 1,
                "plan_status": "cancelled",
            },
        )

        self.assertIsNone(cli._updated_current_plan(current, result))

    def test_recovery_only_command_does_not_build_normal_runtime(self) -> None:
        recovery = _RecordingRecoveryRuntime()
        with (
            patch.object(cli, "build_runtime_service") as build_normal,
            patch.object(cli, "build_recovery_runtime", return_value=recovery) as build,
            patch("builtins.input", side_effect=["recover run_source", "exit"]),
            patch("builtins.print") as output,
        ):
            exit_code = cli.main(
                ["--config", "config/test.json", "--session-id", "session_existing"]
            )

        self.assertEqual(exit_code, 0)
        build_normal.assert_not_called()
        build.assert_called_once_with("config/test.json")
        self.assertEqual(recovery.requests, [("session_existing", "run_source")])
        self.assertTrue(recovery.closed)
        output.assert_any_call("read-only explanation")

    def test_recover_last_is_session_scoped_and_invalid_syntax_fails_closed(self) -> None:
        recovery = _RecordingRecoveryRuntime()
        with (
            patch.object(cli, "build_runtime_service") as build_normal,
            patch.object(cli, "build_recovery_runtime", return_value=recovery),
            patch(
                "builtins.input",
                side_effect=["recover-last extra", "recover-last", "exit"],
            ),
            patch("builtins.print") as output,
        ):
            exit_code = cli.main(["--session-id", "session_existing"])

        self.assertEqual(exit_code, 1)
        build_normal.assert_not_called()
        self.assertEqual(recovery.requests, [("session_existing", None)])
        output.assert_any_call("error: Usage: recover-last")


class _RecordingRuntime:
    def __init__(self, *, error: AppError | None = None) -> None:
        self.error = error
        self.requests: list[RuntimeRequest] = []
        self.closed = False

    def handle(self, request: RuntimeRequest) -> RuntimeResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return RuntimeResult(
            run_id=request.run_id,
            session_id=request.session_id,
            status=RuntimeStatus.OK,
            message=f"handled: {request.user_input}",
        )

    def close(self) -> None:
        self.closed = True


class _RecordingRecoveryRuntime:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str | None]] = []
        self.closed = False

    def explain(self, session_id: str, run_id: str | None = None):
        self.requests.append((session_id, run_id))
        return SimpleNamespace(explanation="read-only explanation")

    def close(self) -> None:
        self.closed = True


if __name__ == "__main__":
    unittest.main()
