"""Stable, content-safe failures for Eval Harness manifests."""

from __future__ import annotations

from enum import StrEnum


class EvalManifestErrorCode(StrEnum):
    NOT_FOUND = "eval_manifest_not_found"
    INVALID_JSON = "eval_manifest_invalid_json"
    INVALID_SCHEMA = "eval_manifest_invalid_schema"
    UNKNOWN_FIELD = "eval_manifest_unknown_field"
    UNKNOWN_SCHEMA_VERSION = "eval_manifest_unknown_schema_version"
    INVALID_REFERENCE = "eval_manifest_invalid_reference"
    DUPLICATE_REFERENCE = "eval_manifest_duplicate_reference"
    UNTRUSTED_FIXTURE = "eval_manifest_untrusted_fixture"
    UNKNOWN_GRADER = "eval_manifest_unknown_grader"
    ID_MISMATCH = "eval_manifest_id_mismatch"


class EvalManifestError(ValueError):
    """Expected manifest validation failure with a stable public code."""

    def __init__(self, message: str, *, code: EvalManifestErrorCode) -> None:
        if not isinstance(code, EvalManifestErrorCode):
            raise ValueError("code must be an EvalManifestErrorCode.")
        super().__init__(message)
        self.message = message
        self.code = code.value


class EvalWorkspaceErrorCode(StrEnum):
    PREPARE_FAILED = "eval_workspace_prepare_failed"
    CLEANUP_FAILED = "eval_workspace_cleanup_failed"


class EvalWorkspaceError(RuntimeError):
    """Safe workspace lifecycle failure without filesystem detail disclosure."""

    def __init__(self, message: str, *, code: EvalWorkspaceErrorCode) -> None:
        if not isinstance(code, EvalWorkspaceErrorCode):
            raise ValueError("code must be an EvalWorkspaceErrorCode.")
        super().__init__(message)
        self.message = message
        self.code = code.value


class EvalStateProbeErrorCode(StrEnum):
    UNKNOWN_PROBE = "eval_state_probe_unknown"
    PROBE_FAILED = "eval_state_probe_failed"
    SNAPSHOT_MISMATCH = "eval_state_snapshot_mismatch"


class EvalStateProbeError(RuntimeError):
    """Safe state-probe failure without repository or source exception leakage."""

    def __init__(self, message: str, *, code: EvalStateProbeErrorCode) -> None:
        if not isinstance(code, EvalStateProbeErrorCode):
            raise ValueError("code must be an EvalStateProbeErrorCode.")
        super().__init__(message)
        self.message = message
        self.code = code.value


class EvalEnvironmentUnavailableError(RuntimeError):
    """Safe live-target failure caused by provider or local environment state."""

    def __init__(
        self,
        message: str = "The live Eval environment is unavailable.",
        *,
        code: str = "eval_environment_unavailable",
    ) -> None:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be non-empty.")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be non-empty.")
        super().__init__(message)
        self.message = message
        self.code = code
