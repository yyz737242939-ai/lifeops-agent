"""Strict local loader for versioned Eval Harness suite and case manifests."""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from app.evals.errors import EvalManifestError, EvalManifestErrorCode
from app.evals.models import (
    EVAL_MANIFEST_SCHEMA_VERSION,
    EvalCase,
    EvalExecutionMode,
    EvalExpectations,
    EvalSuite,
)


_REFERENCE_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SUITE_FIELDS = frozenset(
    {"schema_version", "suite_id", "version", "description", "case_refs", "default_grader_ids"}
)
_CASE_REQUIRED_FIELDS = frozenset(
    {"schema_version", "case_id", "title", "description", "execution_mode", "input", "expectations", "grader_ids"}
)
_CASE_OPTIONAL_FIELDS = frozenset(
    {"fixture_ref", "tags", "timeout_seconds", "required", "regression_ref"}
)
_EXPECTATION_FIELDS = frozenset(EvalExpectations.__dataclass_fields__)


class FileEvalSuiteLoader:
    """Resolve stable refs under a fixed root; never accept manifest paths/imports."""

    def __init__(
        self,
        manifest_root: Path,
        *,
        trusted_fixture_refs: Collection[str] = (),
        trusted_grader_ids: Collection[str],
    ) -> None:
        if not isinstance(manifest_root, Path):
            raise ValueError("manifest_root must be a Path.")
        self._root = manifest_root.resolve()
        self._fixture_refs = _validated_registry(trusted_fixture_refs, "trusted_fixture_refs")
        self._grader_ids = _validated_registry(trusted_grader_ids, "trusted_grader_ids")

    def load(self, suite_ref: str) -> EvalSuite:
        safe_suite_ref = _reference(suite_ref, "suite_ref")
        payload = _read_object(self._root / "suites" / f"{safe_suite_ref}.json")
        _exact_fields(payload, _SUITE_FIELDS, _SUITE_FIELDS)
        _schema_version(payload.get("schema_version"))
        if payload.get("suite_id") != safe_suite_ref:
            raise _error(
                EvalManifestErrorCode.ID_MISMATCH,
                "Suite ID does not match its stable reference.",
            )
        case_refs = _reference_tuple(payload.get("case_refs"), "case_refs")
        default_grader_ids = _string_tuple(
            payload.get("default_grader_ids"), "default_grader_ids"
        )
        self._require_graders(default_grader_ids)
        cases = tuple(self._load_case(case_ref) for case_ref in case_refs)
        try:
            return EvalSuite(
                schema_version=EVAL_MANIFEST_SCHEMA_VERSION,
                suite_id=safe_suite_ref,
                version=payload["version"],
                description=payload["description"],
                cases=cases,
                default_grader_ids=default_grader_ids,
            )
        except (TypeError, ValueError) as exc:
            raise _error(
                EvalManifestErrorCode.INVALID_SCHEMA,
                "Suite manifest contains invalid values.",
            ) from exc

    def _load_case(self, case_ref: str) -> EvalCase:
        payload = _read_object(self._root / "cases" / f"{case_ref}.json")
        _exact_fields(
            payload,
            _CASE_REQUIRED_FIELDS,
            _CASE_REQUIRED_FIELDS | _CASE_OPTIONAL_FIELDS,
        )
        _schema_version(payload.get("schema_version"))
        if payload.get("case_id") != case_ref:
            raise _error(
                EvalManifestErrorCode.ID_MISMATCH,
                "Case ID does not match its stable reference.",
            )
        fixture_ref = payload.get("fixture_ref")
        if fixture_ref is not None:
            fixture_ref = _reference(fixture_ref, "fixture_ref")
            if fixture_ref not in self._fixture_refs:
                raise _error(
                    EvalManifestErrorCode.UNTRUSTED_FIXTURE,
                    "Case fixture reference is not registered.",
                )
        grader_ids = _string_tuple(payload.get("grader_ids"), "grader_ids")
        self._require_graders(grader_ids)
        expectations = _expectations(payload.get("expectations"))
        try:
            return EvalCase(
                schema_version=EVAL_MANIFEST_SCHEMA_VERSION,
                case_id=case_ref,
                title=payload["title"],
                description=payload["description"],
                execution_mode=EvalExecutionMode(payload["execution_mode"]),
                input=payload["input"],
                expectations=expectations,
                grader_ids=grader_ids,
                fixture_ref=fixture_ref,
                tags=_string_tuple(payload.get("tags", []), "tags"),
                timeout_seconds=payload.get("timeout_seconds", 30.0),
                required=payload.get("required", True),
                regression_ref=payload.get("regression_ref"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error(
                EvalManifestErrorCode.INVALID_SCHEMA,
                "Case manifest contains invalid values.",
            ) from exc

    def _require_graders(self, grader_ids: tuple[str, ...]) -> None:
        if any(grader_id not in self._grader_ids for grader_id in grader_ids):
            raise _error(
                EvalManifestErrorCode.UNKNOWN_GRADER,
                "Manifest references an unregistered grader.",
            )


def _expectations(raw: object) -> EvalExpectations:
    if not isinstance(raw, Mapping):
        raise _error(
            EvalManifestErrorCode.INVALID_SCHEMA,
            "expectations must be an object.",
        )
    if set(raw) - _EXPECTATION_FIELDS:
        raise _error(
            EvalManifestErrorCode.UNKNOWN_FIELD,
            "Expectations contain unsupported fields.",
        )
    try:
        return EvalExpectations(**dict(raw))
    except (TypeError, ValueError) as exc:
        raise _error(
            EvalManifestErrorCode.INVALID_SCHEMA,
            "Expectations contain invalid values.",
        ) from exc


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise _error(EvalManifestErrorCode.NOT_FOUND, "Eval manifest was not found.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error(
            EvalManifestErrorCode.INVALID_JSON,
            "Eval manifest is not valid JSON.",
        ) from exc
    if not isinstance(raw, dict):
        raise _error(
            EvalManifestErrorCode.INVALID_SCHEMA,
            "Eval manifest must be an object.",
        )
    return raw


def _exact_fields(
    payload: Mapping[str, Any], required: Collection[str], allowed: Collection[str]
) -> None:
    if set(payload) - set(allowed):
        raise _error(
            EvalManifestErrorCode.UNKNOWN_FIELD,
            "Eval manifest contains unsupported fields.",
        )
    if set(required) - set(payload):
        raise _error(
            EvalManifestErrorCode.INVALID_SCHEMA,
            "Eval manifest is missing required fields.",
        )


def _schema_version(value: object) -> None:
    if value != EVAL_MANIFEST_SCHEMA_VERSION:
        raise _error(
            EvalManifestErrorCode.UNKNOWN_SCHEMA_VERSION,
            "Eval manifest schema version is unsupported.",
        )


def _reference(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _REFERENCE_PATTERN.fullmatch(value) is None:
        raise _error(
            EvalManifestErrorCode.INVALID_REFERENCE,
            f"{field_name} must be a stable reference, not a path or import.",
        )
    return value


def _reference_tuple(value: object, field_name: str) -> tuple[str, ...]:
    values = _string_tuple(value, field_name)
    if not values:
        raise _error(
            EvalManifestErrorCode.INVALID_SCHEMA,
            f"{field_name} must not be empty.",
        )
    return tuple(_reference(item, field_name) for item in values)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise _error(
            EvalManifestErrorCode.INVALID_SCHEMA,
            f"{field_name} must be an array of non-empty strings.",
        )
    result = tuple(value)
    if len(set(result)) != len(result):
        raise _error(
            EvalManifestErrorCode.DUPLICATE_REFERENCE,
            f"{field_name} must not contain duplicates.",
        )
    return result


def _validated_registry(values: Collection[str], field_name: str) -> frozenset[str]:
    if isinstance(values, str):
        raise ValueError(f"{field_name} must be a collection of stable references.")
    refs = tuple(_reference(value, field_name) for value in values)
    if len(set(refs)) != len(refs):
        raise ValueError(f"{field_name} must not contain duplicates.")
    return frozenset(refs)


def _error(code: EvalManifestErrorCode, message: str) -> EvalManifestError:
    return EvalManifestError(message, code=code)
