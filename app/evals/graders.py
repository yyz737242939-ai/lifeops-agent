"""Deterministic graders over shared TraceGraph/RuntimeReport and Eval state delta."""

from __future__ import annotations

from collections.abc import Mapping
from app.evals.contracts import (
    EvalGraderRegistry,
    EvaluationSubject,
    GradeResult,
    GradeStatus,
)
from app.evals.matchers import MatcherOperator, MatcherSpec, evaluate_match
from app.evals.models import EvalCase, FrozenJson
from app.observability.trace_vocabulary import LifeOpsSpanKind, SpanLinkType


GRADER_VERSION = "1.0.0"


class _BaseGrader:
    grader_id: str
    expectation_name: str
    def __init__(self, *, required: bool = True) -> None:
        if not isinstance(required, bool):
            raise ValueError("required must be a bool.")
        self.required = required

    @property
    def version(self) -> str:
        return GRADER_VERSION

    def _expectation(self, case: EvalCase) -> Mapping[str, FrozenJson] | None:
        return getattr(case.expectations, self.expectation_name)

    def _result(
        self,
        case: EvalCase,
        subject: EvaluationSubject,
        status: GradeStatus,
        reason: str,
        *,
        expected: Mapping[str, object] | None = None,
        actual: Mapping[str, object] | None = None,
        facts: tuple[str, ...] = (),
        span_id: str | None = None,
    ) -> GradeResult:
        return GradeResult(
            grade_id=f"{case.case_id}.{self.grader_id}",
            grader_id=self.grader_id,
            grader_version=self.version,
            status=status,
            reason_code=reason,
            safe_explanation=_explanation(self.grader_id, status),
            required=self.required,
            target_trace_id=subject.runtime_report.identity.trace_id,
            target_span_id=span_id,
            fact_references=facts,
            safe_expected=expected or {},
            safe_actual=actual or {},
            score=1.0 if status is GradeStatus.PASSED else 0.0 if status is GradeStatus.FAILED else None,
        )

    def _missing_expectation(
        self, case: EvalCase, subject: EvaluationSubject
    ) -> GradeResult:
        return self._result(
            case,
            subject,
            GradeStatus.SKIPPED,
            f"{self.grader_id}_expectation_missing",
        )

    def _invalid_expectation(
        self, case: EvalCase, subject: EvaluationSubject
    ) -> GradeResult:
        return self._result(
            case,
            subject,
            GradeStatus.ERROR,
            f"{self.grader_id}_expectation_invalid",
        )


class ExecutionPathGrader(_BaseGrader):
    grader_id = "execution-path"
    expectation_name = "execution_path"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        if set(expectation) != {"equals"}:
            return self._invalid_expectation(case, subject)
        report = subject.runtime_report
        path = (
            "recovery"
            if report.recovery_report is not None
            else "planning"
            if report.plan_report or report.workflow_report is not None
            else "direct"
            if report.tool_attempts
            else "final_only"
        )
        return _single_match(
            self,
            case,
            subject,
            MatcherOperator.EQUALS,
            expectation["equals"],
            path,
            facts=("runtime_report.execution_path",),
        )


class PlanLifecycleGrader(_BaseGrader):
    grader_id = "plan-lifecycle"
    expectation_name = "plan_lifecycle"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        if set(expectation) != {"status_by_id"}:
            return self._invalid_expectation(case, subject)
        if not subject.runtime_report.plan_report:
            return self._result(
                case, subject, GradeStatus.UNAVAILABLE, "plan_lifecycle_unavailable"
            )
        statuses: dict[str, str] = {}
        for item in subject.runtime_report.plan_report:
            statuses[item.source_id] = item.status
            step_id = item.attributes.get("step_id")
            if isinstance(step_id, str):
                statuses[step_id] = item.status
        return _single_match(
            self,
            case,
            subject,
            MatcherOperator.STATUS_BY_ID,
            expectation["status_by_id"],
            statuses,
            facts=tuple(item.source_id for item in subject.runtime_report.plan_report),
        )


class WorkflowDependencyGrader(_BaseGrader):
    grader_id = "workflow-dependency"
    expectation_name = "workflow_dependencies"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        if set(expectation) - {"status_by_id", "linked_to"}:
            return self._invalid_expectation(case, subject)
        graph = subject.trace_graph
        if graph is None:
            return self._result(
                case, subject, GradeStatus.UNAVAILABLE, "workflow_dependency_unavailable"
            )
        node_ids = {
            span.span_id: (
                span.attributes.get("lifeops.workflow.node.id")
                or span.attributes.get("lifeops.plan.step.id")
                or span.span_id
            )
            for span in graph.spans_by_id.values()
        }
        statuses = {
            node_ids[span.span_id]: (
                span.attributes.get("lifeops.workflow.node.outcome")
                or span.attributes.get("lifeops.plan.step.outcome")
                or span.status.value
            )
            for span in graph.spans_by_id.values()
            if "lifeops.workflow.node.id" in span.attributes
            or "lifeops.plan.step.id" in span.attributes
        }
        dependencies: dict[str, tuple[str, ...]] = {}
        for link in graph.links:
            if link.link_type is not SpanLinkType.DEPENDS_ON or link.target_span_id is None:
                continue
            source = node_ids.get(link.source_span_id, link.source_span_id)
            target = node_ids.get(link.target_span_id, link.target_span_id)
            dependencies[source] = tuple((*dependencies.get(source, ()), target))
        actual = {"status_by_id": statuses, "linked_to": dependencies}
        return _multi_mapping_match(self, case, subject, expectation, actual)


class ToolCallGrader(_BaseGrader):
    grader_id = "tool-call"
    expectation_name = "tool_calls"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        allowed = {
            "contains_all",
            "contains_none",
            "ordered",
            "count",
            "min_count",
            "max_count",
            "status_by_id",
            "effect_by_id",
            "handler_reached_by_id",
        }
        if set(expectation) - allowed:
            return self._invalid_expectation(case, subject)
        attempts = subject.runtime_report.tool_attempts
        identities = tuple(
            str(item.attributes.get("lifeops.tool.name") or item.source_id)
            for item in attempts
        )
        statuses = {
            identity: str(item.attributes.get("lifeops.tool.outcome") or item.status)
            for identity, item in zip(identities, attempts)
        }
        effects = {
            identity: str(item.attributes["lifeops.tool.effect"])
            for identity, item in zip(identities, attempts)
            if "lifeops.tool.effect" in item.attributes
        }
        reached = {
            identity: item.attributes["lifeops.tool.handler_reached"]
            for identity, item in zip(identities, attempts)
            if "lifeops.tool.handler_reached" in item.attributes
        }
        if "handler_reached_by_id" in expectation:
            try:
                missing_reachability = any(
                    key not in reached
                    for key in _keys(expectation["handler_reached_by_id"])
                )
            except ValueError:
                return self._invalid_expectation(case, subject)
            if missing_reachability:
                return self._result(
                    case, subject, GradeStatus.UNAVAILABLE, "tool_call_handler_reachability_unavailable"
                )
        actual = {
            "identities": identities,
            "status_by_id": statuses,
            "effect_by_id": effects,
            "handler_reached_by_id": reached,
        }
        operator_actual = {
            "contains_all": identities,
            "contains_none": identities,
            "ordered": identities,
            "count": identities,
            "min_count": identities,
            "max_count": identities,
            "status_by_id": statuses,
            "effect_by_id": effects,
            "handler_reached_by_id": reached,
        }
        return _multi_operator_match(
            self, case, subject, expectation, operator_actual, actual,
            facts=tuple(item.source_id for item in attempts),
        )


class StateChangeGrader(_BaseGrader):
    grader_id = "state-change"
    expectation_name = "state_changes"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        if set(expectation) - {"count", "min_count", "max_count", "fact_delta"}:
            return self._invalid_expectation(case, subject)
        if subject.state_delta is None:
            return self._result(
                case, subject, GradeStatus.UNAVAILABLE, "state_change_unavailable"
            )
        changes = subject.state_delta.changes
        delta = {
            f"{item.probe_id}.{item.key}": {
                "before_present": item.before_present,
                "after_present": item.after_present,
                "before": item.before,
                "after": item.after,
            }
            for item in changes
        }
        actual = {"changes": delta, "count": len(changes)}
        change_ids = tuple(f"{item.probe_id}.{item.key}" for item in changes)
        operator_actual = {
            "count": change_ids,
            "min_count": change_ids,
            "max_count": change_ids,
            "fact_delta": delta,
        }
        return _multi_operator_match(self, case, subject, expectation, operator_actual, actual)


class EvidenceGrader(_BaseGrader):
    grader_id = "evidence"
    expectation_name = "evidence"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        if set(expectation) - {"count", "min_count", "max_count", "contains_all", "contains_none", "status_by_id"}:
            return self._invalid_expectation(case, subject)
        evidence = subject.runtime_report.evidence
        kinds = tuple(item.source_kind for item in evidence)
        statuses = {item.source_id: item.status for item in evidence}
        actual = {"source_kinds": kinds, "status_by_id": statuses, "count": len(evidence)}
        evidence_ids = tuple(item.source_id for item in evidence)
        operator_actual = {
            "count": evidence_ids,
            "min_count": evidence_ids,
            "max_count": evidence_ids,
            "contains_all": kinds,
            "contains_none": kinds,
            "status_by_id": statuses,
        }
        return _multi_operator_match(
            self, case, subject, expectation, operator_actual, actual,
            facts=tuple(item.source_id for item in evidence),
        )


class ExecutionFeedbackGrader(_BaseGrader):
    grader_id = "execution-feedback"
    expectation_name = "execution_feedback"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        if set(expectation) - {"equals", "attributes", "stop_status"}:
            return self._invalid_expectation(case, subject)
        feedback = subject.runtime_report.execution_feedback
        if feedback is None:
            return self._result(
                case, subject, GradeStatus.UNAVAILABLE, "execution_feedback_unavailable"
            )
        actual = {
            "equals": feedback.status,
            "attributes": dict(feedback.attributes),
            "stop_status": (
                subject.runtime_report.stop_point.status
                if subject.runtime_report.stop_point is not None
                else "unavailable"
            ),
        }
        return _multi_mapping_match(self, case, subject, expectation, actual, facts=(feedback.source_id,))


class FinalAnswerGroundingGrader(_BaseGrader):
    grader_id = "final-answer-grounding"
    expectation_name = "final_answer"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case)
        if expectation is None:
            return self._missing_expectation(case, subject)
        allowed = {"equals", "min_accepted_claim_count", "max_reason_count"}
        if set(expectation) - allowed:
            return self._invalid_expectation(case, subject)
        validation = subject.runtime_report.final_answer_validation
        if validation is None:
            return self._result(
                case, subject, GradeStatus.UNAVAILABLE, "final_answer_grounding_unavailable"
            )
        actual = {
            "equals": validation.status,
            "min_accepted_claim_count": validation.attributes.get("accepted_claim_count"),
            "max_reason_count": validation.attributes.get("reason_count"),
        }
        for key in ("min_accepted_claim_count", "max_reason_count"):
            if key in expectation and not isinstance(actual[key], int):
                return self._result(
                    case, subject, GradeStatus.UNAVAILABLE, "final_answer_grounding_field_unavailable"
                )
        operator_actual = {
            "equals": actual["equals"],
            "min_accepted_claim_count": tuple(range(int(actual["min_accepted_claim_count"] or 0))),
            "max_reason_count": tuple(range(int(actual["max_reason_count"] or 0))),
        }
        remapped = {
            "equals": expectation.get("equals"),
            "min_count": expectation.get("min_accepted_claim_count"),
            "max_count": expectation.get("max_reason_count"),
        }
        remapped = {key: value for key, value in remapped.items() if value is not None}
        remapped_actual = {
            "equals": operator_actual["equals"],
            "min_count": operator_actual["min_accepted_claim_count"],
            "max_count": operator_actual["max_reason_count"],
        }
        return _multi_operator_match(
            self, case, subject, remapped, remapped_actual, actual,
            facts=(validation.source_id,),
            expected_display=expectation,
        )


class TraceContractGrader(_BaseGrader):
    grader_id = "trace-contract"
    expectation_name = "trace_contract"

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case) or {}
        allowed = {"status", "required_spans", "forbidden_spans", "required_links"}
        if set(expectation) - allowed:
            return self._invalid_expectation(case, subject)
        graph = subject.trace_graph
        if graph is None:
            return self._result(case, subject, GradeStatus.ERROR, "trace_contract_graph_missing")
        span_kinds = tuple(span.lifeops_span_kind.value for span in graph.spans_by_id.values())
        link_types = tuple(link.link_type.value for link in graph.links)
        actual = {
            "status": graph.trace.status.value,
            "required_spans": span_kinds,
            "forbidden_spans": span_kinds,
            "required_links": link_types,
            "integrity_warning_count": len(graph.integrity_warnings),
            "root_parent_absent": graph.root_span.parent_span_id is None,
        }
        if graph.integrity_warnings or graph.root_span.parent_span_id is not None:
            return self._result(
                case, subject, GradeStatus.FAILED, "trace_contract_integrity_failed",
                expected=expectation, actual=actual,
            )
        operators = {
            "status": MatcherOperator.EQUALS,
            "required_spans": MatcherOperator.CONTAINS_ALL,
            "forbidden_spans": MatcherOperator.CONTAINS_NONE,
            "required_links": MatcherOperator.CONTAINS_ALL,
        }
        actual_by_key = {
            "status": actual["status"],
            "required_spans": span_kinds,
            "forbidden_spans": span_kinds,
            "required_links": link_types,
        }
        try:
            passed = all(
                evaluate_match(MatcherSpec(operators[key], expected), actual_by_key[key]).passed
                for key, expected in expectation.items()
            )
        except ValueError:
            return self._invalid_expectation(case, subject)
        return self._result(
            case,
            subject,
            GradeStatus.PASSED if passed else GradeStatus.FAILED,
            "trace_contract_passed" if passed else "trace_contract_mismatch",
            expected=expectation,
            actual=actual,
            facts=(graph.trace.trace_id,),
        )


class PrivacyGrader(_BaseGrader):
    grader_id = "privacy"
    expectation_name = "privacy"
    _default_forbidden = (
        "api_key",
        "authorization",
        "confirmation_token",
        "raw_prompt",
        "raw_output",
        "private_reasoning",
        "context_content",
        "memory_content",
        "profile_content",
    )

    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult:
        expectation = self._expectation(case) or {"forbidden_fields": self._default_forbidden}
        if set(expectation) != {"forbidden_fields"}:
            return self._invalid_expectation(case, subject)
        graph = subject.trace_graph
        if graph is None:
            return self._result(case, subject, GradeStatus.ERROR, "privacy_graph_missing")
        try:
            forbidden = _string_tuple(expectation["forbidden_fields"])
        except ValueError:
            return self._invalid_expectation(case, subject)
        violations: list[str] = []
        mappings = [graph.trace.resource_attributes]
        mappings.extend(span.attributes for span in graph.spans_by_id.values())
        report = subject.runtime_report
        projections = tuple(report.plan_report) + tuple(report.executor_invocations) + tuple(report.tool_attempts)
        projections += tuple(
            item
            for item in (
                report.context_report,
                report.workflow_report,
                report.execution_feedback,
                report.recovery_report,
                report.final_answer_validation,
                report.stop_point,
            )
            if item is not None
        )
        mappings.extend(item.attributes for item in projections)
        for mapping in mappings:
            for key, value in mapping.items():
                lowered = str(key).lower()
                if any(token in lowered for token in forbidden):
                    violations.append(str(key))
                if isinstance(value, str) and any(
                    token in value.lower() for token in forbidden
                ):
                    violations.append(str(key))
        match = evaluate_match(
            MatcherSpec(MatcherOperator.REDACTED, forbidden), tuple(sorted(set(violations)))
        )
        return self._result(
            case,
            subject,
            GradeStatus.PASSED if match.passed else GradeStatus.FAILED,
            "privacy_passed" if match.passed else "privacy_forbidden_field_present",
            expected={"forbidden_fields": forbidden},
            actual={"violations": tuple(sorted(set(violations)))},
            facts=(graph.trace.trace_id,),
        )


def default_grader_registry() -> EvalGraderRegistry:
    return EvalGraderRegistry(
        (
            ExecutionPathGrader(),
            PlanLifecycleGrader(),
            WorkflowDependencyGrader(),
            ToolCallGrader(),
            StateChangeGrader(),
            EvidenceGrader(),
            ExecutionFeedbackGrader(),
            FinalAnswerGroundingGrader(),
            TraceContractGrader(),
            PrivacyGrader(),
        )
    )


def _single_match(
    grader: _BaseGrader,
    case: EvalCase,
    subject: EvaluationSubject,
    operator: MatcherOperator,
    expected: object,
    actual: object,
    *,
    facts: tuple[str, ...] = (),
) -> GradeResult:
    try:
        match = evaluate_match(MatcherSpec(operator, expected), actual)
    except ValueError:
        return grader._invalid_expectation(case, subject)
    return grader._result(
        case,
        subject,
        GradeStatus.PASSED if match.passed else GradeStatus.FAILED,
        f"{grader.grader_id}_{'passed' if match.passed else 'mismatch'}",
        expected={operator.value: match.expected},
        actual={operator.value: match.actual},
        facts=facts,
    )


def _multi_mapping_match(
    grader: _BaseGrader,
    case: EvalCase,
    subject: EvaluationSubject,
    expectation: Mapping[str, object],
    actual: Mapping[str, object],
    *,
    facts: tuple[str, ...] = (),
) -> GradeResult:
    for key, expected in expectation.items():
        if key not in actual:
            return grader._result(
                case, subject, GradeStatus.UNAVAILABLE, f"{grader.grader_id}_field_unavailable"
            )
        operator = MatcherOperator.STATUS_BY_ID if isinstance(expected, Mapping) else MatcherOperator.EQUALS
        try:
            match = evaluate_match(MatcherSpec(operator, expected), actual[key])
        except ValueError:
            return grader._invalid_expectation(case, subject)
        if not match.passed:
            return grader._result(
                case, subject, GradeStatus.FAILED, f"{grader.grader_id}_mismatch",
                expected=dict(expectation), actual=dict(actual), facts=facts,
            )
    return grader._result(
        case, subject, GradeStatus.PASSED, f"{grader.grader_id}_passed",
        expected=dict(expectation), actual=dict(actual), facts=facts,
    )


def _multi_operator_match(
    grader: _BaseGrader,
    case: EvalCase,
    subject: EvaluationSubject,
    expectation: Mapping[str, object],
    operator_actual: Mapping[str, object],
    actual_display: Mapping[str, object],
    *,
    facts: tuple[str, ...] = (),
    expected_display: Mapping[str, object] | None = None,
) -> GradeResult:
    aliases = {
        "effect_by_id": MatcherOperator.STATUS_BY_ID,
        "handler_reached_by_id": MatcherOperator.STATUS_BY_ID,
    }
    try:
        for key, expected in expectation.items():
            operator = aliases[key] if key in aliases else MatcherOperator(key)
            match = evaluate_match(MatcherSpec(operator, expected), operator_actual[key])
            if not match.passed:
                return grader._result(
                    case, subject, GradeStatus.FAILED, f"{grader.grader_id}_mismatch",
                    expected=dict(expected_display or expectation),
                    actual=dict(actual_display), facts=facts,
                )
    except (KeyError, ValueError):
        return grader._invalid_expectation(case, subject)
    return grader._result(
        case, subject, GradeStatus.PASSED, f"{grader.grader_id}_passed",
        expected=dict(expected_display or expectation), actual=dict(actual_display), facts=facts,
    )


def _keys(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        raise ValueError("expected value must be an object.")
    return tuple(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected value must be an array of strings.")
    return value


def _explanation(grader_id: str, status: GradeStatus) -> str:
    return f"{grader_id} completed with {status.value}."
