"""Immutable Eval Harness case, suite, and expectation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re
from types import MappingProxyType
from typing import TypeAlias

from app.common.validation import (
    require_non_empty_string,
    require_unique_non_empty_strings,
)


EVAL_MANIFEST_SCHEMA_VERSION = 1
_STABLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")

JsonScalar: TypeAlias = str | int | float | bool | None
FrozenJson: TypeAlias = JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]


class EvalExecutionMode(StrEnum):
    RUNTIME_REQUEST = "runtime_request"
    PLAN_COMMAND_SEQUENCE = "plan_command_sequence"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class EvalExpectations:
    execution_path: Mapping[str, FrozenJson] | None = None
    plan_lifecycle: Mapping[str, FrozenJson] | None = None
    workflow_dependencies: Mapping[str, FrozenJson] | None = None
    tool_calls: Mapping[str, FrozenJson] | None = None
    state_changes: Mapping[str, FrozenJson] | None = None
    evidence: Mapping[str, FrozenJson] | None = None
    execution_feedback: Mapping[str, FrozenJson] | None = None
    final_answer: Mapping[str, FrozenJson] | None = None
    trace_contract: Mapping[str, FrozenJson] | None = None
    privacy: Mapping[str, FrozenJson] | None = None

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, freeze_eval_object(value, field_name))


@dataclass(frozen=True)
class EvalCase:
    schema_version: int
    case_id: str
    title: str
    description: str
    execution_mode: EvalExecutionMode
    input: Mapping[str, FrozenJson]
    expectations: EvalExpectations
    grader_ids: tuple[str, ...]
    tags: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    required: bool = True
    fixture_ref: str | None = None
    regression_ref: str | None = None

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        require_stable_eval_id(self.case_id, "case_id")
        for field_name in ("title", "description"):
            require_non_empty_string(getattr(self, field_name), field_name)
        if not isinstance(self.execution_mode, EvalExecutionMode):
            raise ValueError("execution_mode must be an EvalExecutionMode.")
        object.__setattr__(self, "input", freeze_eval_object(self.input, "input"))
        if not isinstance(self.expectations, EvalExpectations):
            raise ValueError("expectations must be EvalExpectations.")
        require_unique_non_empty_strings(self.grader_ids, "grader_ids")
        require_unique_non_empty_strings(self.tags, "tags")
        for grader_id in self.grader_ids:
            require_stable_eval_id(grader_id, "grader_ids")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive number.")
        if not isinstance(self.required, bool):
            raise ValueError("required must be a bool.")
        for field_name in ("fixture_ref", "regression_ref"):
            value = getattr(self, field_name)
            if value is not None:
                require_non_empty_string(value, field_name)
        if self.fixture_ref is not None:
            require_stable_eval_id(self.fixture_ref, "fixture_ref")


@dataclass(frozen=True)
class EvalSuite:
    schema_version: int
    suite_id: str
    version: str
    description: str
    cases: tuple[EvalCase, ...]
    default_grader_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        require_stable_eval_id(self.suite_id, "suite_id")
        for field_name in ("version", "description"):
            require_non_empty_string(getattr(self, field_name), field_name)
        if not isinstance(self.cases, tuple) or not self.cases:
            raise ValueError("cases must be a non-empty tuple.")
        if not all(isinstance(case, EvalCase) for case in self.cases):
            raise ValueError("cases must contain only EvalCase values.")
        case_ids = tuple(case.case_id for case in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("cases must not contain duplicate case IDs.")
        require_unique_non_empty_strings(self.default_grader_ids, "default_grader_ids")
        for grader_id in self.default_grader_ids:
            require_stable_eval_id(grader_id, "default_grader_ids")

    @property
    def case_refs(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)


def _require_schema_version(value: int) -> None:
    if value != EVAL_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {EVAL_MANIFEST_SCHEMA_VERSION}.")


def require_stable_eval_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or _STABLE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a stable ID.")


def freeze_eval_object(value: object, field_name: str) -> Mapping[str, FrozenJson]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object.")
    frozen: dict[str, FrozenJson] = {}
    for key, item in value.items():
        require_non_empty_string(key, f"{field_name} key")
        frozen[key] = freeze_eval_value(item, f"{field_name}.{key}")
    return MappingProxyType(frozen)


def freeze_eval_value(value: object, field_name: str) -> FrozenJson:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        return freeze_eval_object(value, field_name)
    if isinstance(value, (list, tuple)):
        return tuple(
            freeze_eval_value(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{field_name} must contain only JSON-compatible values.")
