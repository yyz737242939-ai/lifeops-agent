"""Native single-call Tool execution gateway."""

from __future__ import annotations

from app.common.ids import new_id
from app.observability.logger import TraceSink
from app.observability.telemetry import add_span_event, optional_span
from app.observability.trace_models import ArtifactReference
from app.observability.trace_vocabulary import ArtifactSensitivity, LifeOpsSpanKind
from app.tools.errors import ToolGatewayError
from app.tools.guardrails import evaluate_post_execution, evaluate_pre_execution
from app.tools.models import (
    AllowedToolSet,
    ConfirmedAction,
    GuardrailAction,
    GuardrailDecision,
    ToolCall,
    ToolCallStatus,
    ToolError,
    ToolResult,
)
from app.tools.registry import ToolRegistry


class ToolGateway:
    """Run one ToolCall through guardrails and one registered handler."""

    def __init__(
        self,
        registry: ToolRegistry,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise ToolGatewayError(
                "registry must be a ToolRegistry.",
                code="tool_gateway_invalid_registry",
            )
        self._registry = registry

    def execute(
        self,
        call: ToolCall,
        allowed_tools: AllowedToolSet,
        *,
        confirmation: ConfirmedAction | None = None,
        run_id: str | None = None,
        trace: TraceSink | None = None,
    ) -> ToolResult:
        """Execute one authorized call without exposing handler exceptions."""

        effect = "unknown"
        if isinstance(call, ToolCall) and self._registry.contains(call.tool_name):
            effect = self._registry.get(call.tool_name).effect.value
        with optional_span(
            trace,
            name=f"tool.{call.tool_name if isinstance(call, ToolCall) else 'invalid'}",
            kind=LifeOpsSpanKind.TOOL,
            attributes={
                "lifeops.tool.call_id": call.call_id if isinstance(call, ToolCall) else "invalid",
                "lifeops.tool.name": call.tool_name if isinstance(call, ToolCall) else "invalid",
                "lifeops.tool.effect": effect,
            },
        ):
            return self._execute(
                call,
                allowed_tools,
                confirmation=confirmation,
                run_id=run_id,
                trace=trace,
            )

    def _execute(
        self,
        call: ToolCall,
        allowed_tools: AllowedToolSet,
        *,
        confirmation: ConfirmedAction | None,
        run_id: str | None,
        trace: TraceSink | None,
    ) -> ToolResult:

        if not isinstance(call, ToolCall):
            raise ToolGatewayError(
                "call must be a ToolCall.",
                code="tool_gateway_invalid_call",
            )
        if not isinstance(allowed_tools, AllowedToolSet):
            raise ToolGatewayError(
                "allowed_tools must be an AllowedToolSet.",
                code="tool_gateway_invalid_allowed_tools",
            )

        _trace(trace, "tool.call.requested", call_id=call.call_id, tool_name=call.tool_name)
        with optional_span(
            trace,
            name="guardrail.pre",
            kind=LifeOpsSpanKind.GUARDRAIL,
            attributes={"guardrail.stage": "pre", "lifeops.tool.name": call.tool_name},
        ):
            pre = evaluate_pre_execution(
                call,
                allowed_tools,
                self._registry,
                confirmation=confirmation,
                run_id=run_id,
            )
        _trace_guardrail(trace, pre)
        if pre.action != GuardrailAction.ALLOW:
            status = (
                ToolCallStatus.REQUIRES_CONFIRMATION
                if pre.action == GuardrailAction.REQUIRES_CONFIRMATION
                else ToolCallStatus.DENIED
            )
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=status,
                error=ToolError(pre.reason_code, pre.reason),
            )
            return self._finish(result, trace)

        registered = self._registry.resolve(call.tool_name)
        try:
            result = registered.handler(call)
        except Exception:
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.FAILED,
                error=ToolError(
                    "tool_handler_failed",
                    "Tool handler raised an unexpected error.",
                ),
            )
            return self._finish(result, trace)
        if not isinstance(result, ToolResult):
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.FAILED,
                error=ToolError(
                    "tool_handler_invalid_result",
                    "Tool handler did not return a ToolResult.",
                ),
            )
            return self._finish(result, trace)

        with optional_span(
            trace,
            name="guardrail.post",
            kind=LifeOpsSpanKind.GUARDRAIL,
            attributes={"guardrail.stage": "post", "lifeops.tool.name": call.tool_name},
        ):
            post = evaluate_post_execution(call, result, self._registry)
        _trace_guardrail(trace, post)
        if post.action != GuardrailAction.ALLOW:
            if result.status != ToolCallStatus.SUCCEEDED:
                return self._finish(result, trace)
            result = ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.FAILED,
                error=ToolError(post.reason_code, post.reason),
            )
        return self._finish(result, trace)

    def _finish(
        self,
        result: ToolResult,
        trace: TraceSink | None,
    ) -> ToolResult:
        _trace_result(trace, result)
        add_span_event(
            trace,
            "tool.result.recorded",
            {
                "lifeops.tool.outcome": result.status.value,
                "lifeops.evidence.count": len(result.evidence),
            },
        )
        add_artifact = getattr(trace, "add_artifact_reference", None)
        context = getattr(trace, "trace_context", None)
        if callable(add_artifact) and context is not None:
            for evidence in result.evidence:
                if evidence.reference is None:
                    continue
                add_artifact(
                    ArtifactReference(
                        artifact_id=new_id("artifact"),
                        trace_id=context.trace_id,
                        span_id=context.current_span_id,
                        artifact_type="tool_evidence",
                        storage_kind="external_reference",
                        safe_reference=evidence.reference,
                        sensitivity=ArtifactSensitivity.INTERNAL,
                    )
                )
        return result


def _trace_guardrail(trace: TraceSink | None, decision: GuardrailDecision) -> None:
    _trace(
        trace,
        "tool.guardrail.decided",
        stage=decision.stage.value,
        action=decision.action.value,
        reason_code=decision.reason_code,
        tool_name=decision.tool_name,
    )


def _trace_result(trace: TraceSink | None, result: ToolResult) -> None:
    event_type = (
        "tool.call.completed"
        if result.status == ToolCallStatus.SUCCEEDED
        else "tool.call.failed"
    )
    payload: dict[str, object] = {
        "call_id": result.call_id,
        "tool_name": result.tool_name,
        "status": result.status.value,
        "evidence_count": len(result.evidence),
    }
    if result.error is not None:
        payload["error_code"] = result.error.code
    _trace(trace, event_type, **payload)


def _trace(trace: TraceSink | None, event_type: str, **payload: object) -> None:
    if trace is not None:
        trace.append(event_type, payload)
