from __future__ import annotations

import unittest

from app.evals import (
    EvalGraderRegistry,
    MatcherOperator,
    MatcherSpec,
    evaluate_match,
)


class EvalMatcherContractsTest(unittest.TestCase):
    def test_all_v0_matcher_operators_are_deterministic(self) -> None:
        cases = (
            (MatcherOperator.EQUALS, "ok", "ok", True),
            (MatcherOperator.CONTAINS_ALL, ("a", "c"), ("a", "b", "c"), True),
            (MatcherOperator.CONTAINS_NONE, ("x",), ("a", "b"), True),
            (MatcherOperator.ORDERED, ("a", "c"), ("a", "b", "c"), True),
            (MatcherOperator.COUNT, 2, ("a", "b"), True),
            (MatcherOperator.MIN_COUNT, 2, ("a", "b", "c"), True),
            (MatcherOperator.MAX_COUNT, 2, ("a",), True),
            (MatcherOperator.STATUS_BY_ID, {"a": "ok"}, {"a": "ok", "b": "failed"}, True),
            (
                MatcherOperator.FACT_DELTA,
                {"task.count": {"after": 2}},
                {"task.count": {"before": 1, "after": 2}},
                True,
            ),
            (MatcherOperator.LINKED_TO, {"d": ("b", "c")}, {"d": ("b", "c")}, True),
            (MatcherOperator.CLAIM_SUPPORTED, True, True, True),
            (MatcherOperator.TOPOLOGY, {"root": "runtime"}, {"root": "runtime", "tools": 1}, True),
            (MatcherOperator.REDACTED, ("api_key",), ("trace_id",), True),
            (MatcherOperator.EQUALS, "ok", "failed", False),
        )
        for operator, expected, actual, passed in cases:
            with self.subTest(operator=operator, expected=expected):
                result = evaluate_match(MatcherSpec(operator, expected), actual)
                self.assertIs(result.passed, passed)
                self.assertEqual(
                    result.reason_code,
                    f"matcher_{operator.value}_{'passed' if passed else 'failed'}",
                )

    def test_matchers_fail_closed_on_wrong_typed_shapes(self) -> None:
        invalid = (
            (MatcherOperator.COUNT, "one", ("a",)),
            (MatcherOperator.STATUS_BY_ID, ("a",), {"a": "ok"}),
            (MatcherOperator.CLAIM_SUPPORTED, "yes", True),
            (MatcherOperator.CONTAINS_ALL, ("a",), "a"),
        )
        for operator, expected, actual in invalid:
            with self.subTest(operator=operator):
                with self.assertRaises(ValueError):
                    evaluate_match(MatcherSpec(operator, expected), actual)

    def test_grader_registry_rejects_duplicates_and_unknown_ids(self) -> None:
        first = _Grader("trace-contract")
        registry = EvalGraderRegistry((first, _Grader("privacy")))
        self.assertIs(registry.get("trace-contract"), first)
        self.assertEqual(registry.grader_ids, ("trace-contract", "privacy"))
        with self.assertRaises(ValueError):
            EvalGraderRegistry((first, first))
        with self.assertRaises(ValueError):
            registry.get("tool-call")


class _Grader:
    version = "1.0.0"

    def __init__(self, grader_id: str) -> None:
        self.grader_id = grader_id

    def grade(self, case, subject):
        raise AssertionError("not called")


if __name__ == "__main__":
    unittest.main()
