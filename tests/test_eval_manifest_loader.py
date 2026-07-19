from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from app.evals import (
    EVAL_MANIFEST_SCHEMA_VERSION,
    EvalCase,
    EvalExecutionMode,
    EvalExpectations,
    EvalManifestError,
    EvalManifestErrorCode,
    EvalSuite,
    FileEvalSuiteLoader,
)


class EvalManifestModelsTest(unittest.TestCase):
    def test_case_and_suite_are_deeply_immutable(self) -> None:
        case = EvalCase(
            schema_version=EVAL_MANIFEST_SCHEMA_VERSION,
            case_id="direct-final",
            title="Direct final",
            description="Final answer without a Tool call.",
            execution_mode=EvalExecutionMode.RUNTIME_REQUEST,
            input={"message": "hello", "turns": [{"role": "user"}]},
            expectations=EvalExpectations(
                trace_contract={"topology": {"required": ["runtime"]}}
            ),
            grader_ids=("trace-contract",),
        )
        suite = EvalSuite(
            schema_version=EVAL_MANIFEST_SCHEMA_VERSION,
            suite_id="runtime-core",
            version="1.0.0",
            description="Runtime core cases.",
            cases=(case,),
        )

        self.assertEqual(suite.case_refs, ("direct-final",))
        self.assertEqual(case.input["turns"], ({"role": "user"},))
        with self.assertRaises(FrozenInstanceError):
            case.title = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            case.input["message"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            case.expectations.trace_contract["topology"] = {}  # type: ignore[index,union-attr]

    def test_models_reject_unknown_versions_duplicates_and_non_json_input(self) -> None:
        expectations = EvalExpectations()
        invalid = (
            {"schema_version": 2},
            {"case_id": "../case-1"},
            {"grader_ids": ("trace-contract", "trace-contract")},
            {"timeout_seconds": 0},
            {"input": {"callable": object()}},
        )
        base = {
            "schema_version": 1,
            "case_id": "case-1",
            "title": "Case",
            "description": "Description",
            "execution_mode": EvalExecutionMode.RECOVERY,
            "input": {},
            "expectations": expectations,
            "grader_ids": ("trace-contract",),
        }
        for override in invalid:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    EvalCase(**(base | override))


class FileEvalSuiteLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "suites").mkdir()
        (self.root / "cases").mkdir()
        self.loader = FileEvalSuiteLoader(
            self.root,
            trusted_fixture_refs=("direct-read", "planning-basic"),
            trusted_grader_ids=("trace-contract", "tool-call"),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_loads_three_execution_modes_from_stable_refs(self) -> None:
        refs = (
            ("direct-final", "runtime_request", None),
            ("planning-preview", "plan_command_sequence", "planning-basic"),
            ("recovery-last", "recovery", None),
        )
        for case_ref, mode, fixture_ref in refs:
            payload = _case(case_ref, mode=mode)
            if fixture_ref is not None:
                payload["fixture_ref"] = fixture_ref
            self._write("cases", case_ref, payload)
        self._write(
            "suites",
            "runtime-core",
            _suite("runtime-core", [item[0] for item in refs]),
        )

        suite = self.loader.load("runtime-core")

        self.assertEqual(suite.case_refs, tuple(item[0] for item in refs))
        self.assertEqual(
            tuple(case.execution_mode for case in suite.cases),
            tuple(EvalExecutionMode(item[1]) for item in refs),
        )
        self.assertEqual(suite.cases[0].tags, ("offline",))
        self.assertEqual(
            suite.cases[0].expectations.trace_contract["required"],
            ("runtime",),
        )

    def test_unknown_missing_and_duplicate_fields_fail_closed(self) -> None:
        cases = (
            (
                _suite("runtime-core", ["direct-final"]) | {"import": "module.call"},
                EvalManifestErrorCode.UNKNOWN_FIELD,
            ),
            (
                {key: value for key, value in _suite("runtime-core", ["direct-final"]).items() if key != "version"},
                EvalManifestErrorCode.INVALID_SCHEMA,
            ),
            (
                _suite("runtime-core", ["direct-final", "direct-final"]),
                EvalManifestErrorCode.DUPLICATE_REFERENCE,
            ),
            (
                _suite("runtime-core", ["../direct-final"]),
                EvalManifestErrorCode.INVALID_REFERENCE,
            ),
            (
                _suite("runtime-core", ["direct-final"]) | {"schema_version": 2},
                EvalManifestErrorCode.UNKNOWN_SCHEMA_VERSION,
            ),
        )
        for payload, code in cases:
            with self.subTest(code=code):
                self._write("suites", "runtime-core", payload)
                self._assert_code(code, lambda: self.loader.load("runtime-core"))

    def test_case_expectations_fixture_and_grader_are_allowlisted(self) -> None:
        variants = (
            (
                _case("direct-final") | {"intent": {"equals": "chat"}},
                EvalManifestErrorCode.UNKNOWN_FIELD,
            ),
            (
                _case("direct-final") | {"expectations": {"intent": {"equals": "chat"}}},
                EvalManifestErrorCode.UNKNOWN_FIELD,
            ),
            (
                _case("direct-final") | {"fixture_ref": "unregistered-fixture"},
                EvalManifestErrorCode.UNTRUSTED_FIXTURE,
            ),
            (
                _case("direct-final") | {"grader_ids": ["unknown-grader"]},
                EvalManifestErrorCode.UNKNOWN_GRADER,
            ),
            (
                _case("other-id"),
                EvalManifestErrorCode.ID_MISMATCH,
            ),
        )
        self._write("suites", "runtime-core", _suite("runtime-core", ["direct-final"]))
        for payload, code in variants:
            with self.subTest(code=code):
                self._write("cases", "direct-final", payload)
                self._assert_code(code, lambda: self.loader.load("runtime-core"))

    def test_external_paths_import_syntax_invalid_json_and_missing_ref_are_rejected(self) -> None:
        for ref in ("../runtime-core", "runtime/core", "module:factory", "C:\\suite"):
            with self.subTest(ref=ref):
                self._assert_code(
                    EvalManifestErrorCode.INVALID_REFERENCE,
                    lambda ref=ref: self.loader.load(ref),
                )

        (self.root / "suites" / "broken.json").write_text("{", encoding="utf-8")
        self._assert_code(
            EvalManifestErrorCode.INVALID_JSON,
            lambda: self.loader.load("broken"),
        )
        self._assert_code(
            EvalManifestErrorCode.NOT_FOUND,
            lambda: self.loader.load("missing"),
        )

    def _write(self, kind: str, ref: str, payload: object) -> None:
        (self.root / kind / f"{ref}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def _assert_code(self, code: EvalManifestErrorCode, action) -> None:
        with self.assertRaises(EvalManifestError) as raised:
            action()
        self.assertEqual(raised.exception.code, code.value)


def _suite(suite_id: str, case_refs: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite_id": suite_id,
        "version": "1.0.0",
        "description": "Runtime core suite.",
        "case_refs": case_refs,
        "default_grader_ids": ["trace-contract"],
    }


def _case(
    case_id: str,
    *,
    mode: str = "runtime_request",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "case_id": case_id,
        "title": "Case title",
        "description": "Case description.",
        "execution_mode": mode,
        "input": {"message": "hello"},
        "expectations": {"trace_contract": {"required": ["runtime"]}},
        "grader_ids": ["trace-contract"],
        "tags": ["offline"],
    }


if __name__ == "__main__":
    unittest.main()
