from __future__ import annotations

import unittest

from app.context.budget import (
    ESTIMATED_CHARACTERS_PER_TOKEN,
    estimate_tokens,
    normalize_text_for_token_estimate,
)
from app.context.models import ContextBudget


class ContextBudgetTest(unittest.TestCase):
    def test_token_estimate_is_normalized_deterministic_and_ceil_bounded(self) -> None:
        self.assertEqual(ESTIMATED_CHARACTERS_PER_TOKEN, 4)
        self.assertEqual(normalize_text_for_token_estimate("  hello   world\n"), "hello world")
        cases = (
            ("", 0),
            ("   \n\t", 0),
            ("a", 1),
            ("abcd", 1),
            ("abcde", 2),
            ("  hello   world\n", 3),
            ("你好世界", 1),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(estimate_tokens(text), expected)
                self.assertEqual(estimate_tokens(text), expected)

        with self.assertRaises(ValueError):
            estimate_tokens(None)  # type: ignore[arg-type]

    def test_budget_accepts_fixed_zero_optional_caps(self) -> None:
        budget = ContextBudget(
            max_total_tokens=1000,
            max_recent_turns=0,
            max_summary_tokens=0,
            max_profile_tokens=0,
            max_memory_items=0,
            max_memory_tokens=0,
            max_current_input_tokens=500,
        )

        self.assertEqual(budget.max_total_tokens, 1000)
        self.assertEqual(budget.max_memory_items, 0)

    def test_budget_rejects_invalid_types_ranges_and_subcaps(self) -> None:
        valid = {
            "max_total_tokens": 1000,
            "max_recent_turns": 8,
            "max_summary_tokens": 300,
            "max_profile_tokens": 200,
            "max_memory_items": 5,
            "max_memory_tokens": 200,
            "max_current_input_tokens": 400,
        }
        invalid = (
            ("max_total_tokens", 0),
            ("max_total_tokens", True),
            ("max_recent_turns", -1),
            ("max_recent_turns", 1.5),
            ("max_summary_tokens", -1),
            ("max_profile_tokens", 1001),
            ("max_memory_items", -1),
            ("max_memory_tokens", 1001),
            ("max_current_input_tokens", 0),
            ("max_current_input_tokens", 1001),
        )
        for field_name, value in invalid:
            values = dict(valid)
            values[field_name] = value
            with self.subTest(field_name=field_name, value=value), self.assertRaises(
                ValueError
            ):
                ContextBudget(**values)


if __name__ == "__main__":
    unittest.main()
