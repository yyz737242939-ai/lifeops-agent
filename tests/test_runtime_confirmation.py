from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.runtime.confirmation import CliActionConfirmationProvider
from app.tools.models import (
    ToolCall,
    ToolDefinition,
    ToolEffect,
    ToolRisk,
)


class CliActionConfirmationProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
        self.call = ToolCall(
            "call_1",
            "memory.save",
            {"content": "窗口座位", "tags": ["travel"]},
        )
        self.definition = _definition(ToolEffect.WRITE)

    def test_explicit_yes_returns_exact_short_lived_confirmation(self) -> None:
        prompts: list[str] = []
        provider = CliActionConfirmationProvider(
            input_reader=lambda prompt: prompts.append(prompt) or "yes",
            clock=lambda: self.now,
            ttl=timedelta(minutes=3),
        )

        confirmation = provider.confirm("run_1", self.call, self.definition)

        self.assertIsNotNone(confirmation)
        self.assertTrue(confirmation.matches("run_1", self.call, now=self.now))
        self.assertEqual(
            confirmation.expires_at,
            "2026-07-16T08:03:00+00:00",
        )
        self.assertIn("memory.save", prompts[0])
        self.assertIn('"content":"窗口座位"', prompts[0])
        self.assertIn("risk: high", prompts[0])

    def test_reject_empty_eof_and_input_error_fail_closed(self) -> None:
        readers = (
            lambda prompt: "no",
            lambda prompt: "",
            _raise_eof,
            _raise_os_error,
        )
        for reader in readers:
            with self.subTest(reader=reader):
                provider = CliActionConfirmationProvider(
                    input_reader=reader,
                    clock=lambda: self.now,
                )
                self.assertIsNone(
                    provider.confirm("run_1", self.call, self.definition)
                )

    def test_non_write_and_invalid_clock_fail_closed_without_prompt(self) -> None:
        prompts: list[str] = []
        read_provider = CliActionConfirmationProvider(
            input_reader=lambda prompt: prompts.append(prompt) or "yes",
            clock=lambda: self.now,
        )
        invalid_clock_provider = CliActionConfirmationProvider(
            input_reader=lambda prompt: prompts.append(prompt) or "yes",
            clock=lambda: datetime(2026, 7, 16, 8, 0),
        )

        self.assertIsNone(
            read_provider.confirm(
                "run_1",
                self.call,
                _definition(ToolEffect.READ),
            )
        )
        self.assertIsNone(
            invalid_clock_provider.confirm("run_1", self.call, self.definition)
        )
        self.assertEqual(prompts, [])


def _definition(effect: ToolEffect) -> ToolDefinition:
    return ToolDefinition(
        name="memory.save",
        description="Save one Memory.",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": True,
        },
        output_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": True,
        },
        effect=effect,
        risk=ToolRisk.HIGH,
    )


def _raise_eof(prompt: str) -> str:
    raise EOFError


def _raise_os_error(prompt: str) -> str:
    raise OSError("input unavailable")


if __name__ == "__main__":
    unittest.main()
