"""Small deterministic matchers over typed, safe evaluation values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.evals.models import FrozenJson, freeze_eval_value


class MatcherOperator(StrEnum):
    EQUALS = "equals"
    CONTAINS_ALL = "contains_all"
    CONTAINS_NONE = "contains_none"
    ORDERED = "ordered"
    COUNT = "count"
    MIN_COUNT = "min_count"
    MAX_COUNT = "max_count"
    STATUS_BY_ID = "status_by_id"
    FACT_DELTA = "fact_delta"
    LINKED_TO = "linked_to"
    CLAIM_SUPPORTED = "claim_supported"
    TOPOLOGY = "topology"
    REDACTED = "redacted"


@dataclass(frozen=True)
class MatcherSpec:
    operator: MatcherOperator
    expected: FrozenJson

    def __post_init__(self) -> None:
        if not isinstance(self.operator, MatcherOperator):
            raise ValueError("operator must be MatcherOperator.")
        object.__setattr__(self, "expected", freeze_eval_value(self.expected, "expected"))


@dataclass(frozen=True)
class MatchResult:
    passed: bool
    reason_code: str
    expected: FrozenJson
    actual: FrozenJson

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool.")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("reason_code must be a non-empty string.")
        object.__setattr__(self, "expected", freeze_eval_value(self.expected, "expected"))
        object.__setattr__(self, "actual", freeze_eval_value(self.actual, "actual"))


def evaluate_match(spec: MatcherSpec, actual: object) -> MatchResult:
    if not isinstance(spec, MatcherSpec):
        raise ValueError("spec must be MatcherSpec.")
    safe_actual = freeze_eval_value(actual, "actual")
    expected = spec.expected
    operator = spec.operator
    if operator is MatcherOperator.EQUALS:
        passed = safe_actual == expected
    elif operator in (MatcherOperator.CONTAINS_ALL, MatcherOperator.CONTAINS_NONE):
        actual_items = _sequence(safe_actual, "actual")
        expected_items = _sequence(expected, "expected")
        present = all(item in actual_items for item in expected_items)
        passed = present if operator is MatcherOperator.CONTAINS_ALL else not any(
            item in actual_items for item in expected_items
        )
    elif operator is MatcherOperator.ORDERED:
        passed = _is_subsequence(
            _sequence(expected, "expected"), _sequence(safe_actual, "actual")
        )
    elif operator in (
        MatcherOperator.COUNT,
        MatcherOperator.MIN_COUNT,
        MatcherOperator.MAX_COUNT,
    ):
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            raise ValueError("count matcher expected value must be non-negative int.")
        count = len(_sequence(safe_actual, "actual"))
        safe_actual = count
        passed = (
            count == expected
            if operator is MatcherOperator.COUNT
            else count >= expected
            if operator is MatcherOperator.MIN_COUNT
            else count <= expected
        )
    elif operator in (
        MatcherOperator.STATUS_BY_ID,
        MatcherOperator.FACT_DELTA,
        MatcherOperator.LINKED_TO,
        MatcherOperator.TOPOLOGY,
    ):
        passed = _mapping_subset(
            _mapping(expected, "expected"), _mapping(safe_actual, "actual")
        )
    elif operator is MatcherOperator.CLAIM_SUPPORTED:
        if not isinstance(expected, bool) or not isinstance(safe_actual, bool):
            raise ValueError("claim_supported requires bool values.")
        passed = safe_actual is expected
    elif operator is MatcherOperator.REDACTED:
        expected_items = _sequence(expected, "expected")
        actual_items = _sequence(safe_actual, "actual")
        passed = not any(item in actual_items for item in expected_items)
    else:
        raise ValueError("matcher operator is unsupported.")
    return MatchResult(
        passed=passed,
        reason_code=f"matcher_{operator.value}_{'passed' if passed else 'failed'}",
        expected=expected,
        actual=safe_actual,
    )


def _sequence(value: FrozenJson, field_name: str) -> tuple[FrozenJson, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be an array.")
    return value


def _mapping(value: FrozenJson, field_name: str) -> Mapping[str, FrozenJson]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object.")
    return value


def _mapping_subset(
    expected: Mapping[str, FrozenJson], actual: Mapping[str, FrozenJson]
) -> bool:
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping) or not _mapping_subset(
                expected_value, actual_value
            ):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _is_subsequence(
    expected: Sequence[FrozenJson], actual: Sequence[FrozenJson]
) -> bool:
    cursor = iter(actual)
    return all(any(candidate == item for candidate in cursor) for item in expected)
