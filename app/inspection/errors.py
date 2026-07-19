"""Stable validation failures for read-only Inspector contracts."""

from __future__ import annotations

from enum import StrEnum


class InspectorValidationCode(StrEnum):
    INVALID_FIELD = "inspection_invalid_field"
    TARGET_EXACTLY_ONE = "inspection_target_exactly_one"
    VIEWS_REQUIRED = "inspection_views_required"
    DUPLICATE_VIEW = "inspection_duplicate_view"
    SPAN_REQUIRES_DETAILS = "inspection_span_requires_details"
    SPAN_TARGET_AMBIGUOUS = "inspection_span_target_ambiguous"
    SENSITIVE_REQUIRES_DETAILS = "inspection_sensitive_requires_details"
    REPORTS_REQUIRED = "inspection_reports_required"
    DUPLICATE_REPORT = "inspection_duplicate_report"
    TARGET_MISMATCH = "inspection_target_mismatch"
    ANNOTATION_TARGET_MISMATCH = "inspection_annotation_target_mismatch"


class InspectorErrorCode(StrEnum):
    TARGET_NOT_FOUND = "inspection_target_not_found"
    FACT_PROVIDER_FAILED = "inspection_fact_provider_failed"
    REPORT_BUILDER_FAILED = "inspection_report_builder_failed"


class InspectorValidationError(ValueError):
    """Expected contract failure with a content-free, stable error code."""

    def __init__(self, message: str, *, code: InspectorValidationCode) -> None:
        if not isinstance(code, InspectorValidationCode):
            raise ValueError("code must be an InspectorValidationCode.")
        super().__init__(message)
        self.message = message
        self.code = code.value


class InspectorError(RuntimeError):
    """Safe read-orchestration failure without source exception disclosure."""

    def __init__(self, message: str, *, code: InspectorErrorCode) -> None:
        if not isinstance(code, InspectorErrorCode):
            raise ValueError("code must be an InspectorErrorCode.")
        super().__init__(message)
        self.message = message
        self.code = code.value
