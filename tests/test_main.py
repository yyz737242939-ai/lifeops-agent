from __future__ import annotations

import unittest
from unittest.mock import patch

import main as cli
from app.common.errors import AppError
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus


class MainCliTest(unittest.TestCase):
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
        build.assert_called_once_with("config/test.json")
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


if __name__ == "__main__":
    unittest.main()
