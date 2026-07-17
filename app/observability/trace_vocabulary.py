"""Stable vocabulary for the LifeOps Trace Contract v1."""

from __future__ import annotations

from enum import StrEnum


TRACE_SCHEMA_VERSION = 1


class TraceSource(StrEnum):
    INTERACTIVE = "interactive"
    COMPILED_E2E = "compiled_e2e"
    REAL_LLM_SMOKE = "real_llm_smoke"
    EVAL = "eval"


class TraceStatus(StrEnum):
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class LifeOpsSpanKind(StrEnum):
    RUNTIME = "RUNTIME"
    INTENT = "INTENT"
    POLICY = "POLICY"
    SKILL = "SKILL"
    PLANNER = "PLANNER"
    EXECUTOR = "EXECUTOR"
    LLM = "LLM"
    TOOL = "TOOL"
    GUARDRAIL = "GUARDRAIL"
    CONTEXT = "CONTEXT"
    MEMORY = "MEMORY"
    RECOVERY = "RECOVERY"
    EVALUATOR = "EVALUATOR"


class SpanLinkType(StrEnum):
    PLAN_CONTINUATION = "plan_continuation"
    RECOVERY_OF = "recovery_of"
    EVALUATION_OF = "evaluation_of"
    DERIVED_FROM = "derived_from"
    DEPENDS_ON = "depends_on"


class ArtifactSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class AnnotationKind(StrEnum):
    DIAGNOSTIC = "diagnostic"
    EVALUATION = "evaluation"
    HUMAN_FEEDBACK = "human_feedback"
    WARNING = "warning"


class AnnotationProducer(StrEnum):
    DETERMINISTIC_RULE = "deterministic_rule"
    LLM_JUDGE = "llm_judge"
    HUMAN = "human"


class AnnotationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    INFORMATIONAL = "informational"
    SKIPPED = "skipped"
    ERROR = "error"


class AnnotationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
