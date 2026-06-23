from typing import Any

from app.observability.session import append_log_record


class EventLogger:
    """Emit compact, structured milestones from the Agent runtime."""

    def _write_log_event(self, event: str, state: Any, **fields: Any) -> None:
        append_log_record(
            "events",
            event,
            {"run_id": state.run_id, **fields},
        )

    def log_run_started(self, run_state: Any, limits: Any) -> None:
        self._write_log_event("run.started", run_state, limits=limits)

    def log_user_input(self, run_state: Any, content: str) -> None:
        self._write_log_event("run.user_input", run_state, role="user", content=content)

    def log_routing_resolved(
        self,
        run_state: Any,
        *,
        available_skills: Any,
        routing: Any,
        skill_state: Any,
        prompt_chars: int,
    ) -> None:
        self._write_log_event(
            "routing.resolved",
            run_state,
            available_skills=list(available_skills),
            directly_selected=list(skill_state.directly_selected),
            inherited_skills=list(skill_state.inherited_skills),
            loaded_skills=list(skill_state.loaded_skills),
            previous_active_skills=list(skill_state.previous_active_skills),
            next_active_skills=list(skill_state.next_active_skills),
            inheritance_used=skill_state.inheritance_used,
            state_cleared=skill_state.state_cleared,
            state_resolution=skill_state.resolution,
            scores=routing.scores,
            reasons={name: list(items) for name, items in routing.reasons.items()},
            fallback_used=routing.fallback_used,
            prompt_chars=prompt_chars,
        )

    def log_capabilities_built(
        self, run_state: Any, capabilities: Any, tools: Any
    ) -> None:
        self._write_log_event(
            "capability.built",
            run_state,
            loaded_skills=list(capabilities.loaded_skills),
            visible_tool_names=[schema["name"] for schema in capabilities.tool_schemas],
            capability_sources={
                name: list(sources)
                for name, sources in capabilities.capability_sources.items()
            },
            tool_schema_count=capabilities.schema_count,
            tool_schema_chars=capabilities.schema_chars,
            tool_metadata={
                name: tools[name].metadata()
                for name in capabilities.allowed_tool_names
                if name in tools
            },
            fallback_used=capabilities.fallback_used,
        )

    def log_llm_requested(self, run_state: Any, loop: int, context: Any) -> None:
        self._write_log_event(
            "llm.requested",
            run_state,
            loop=loop,
            context=context,
            run_state=run_state.to_dict(include_actions=False),
        )

    def log_llm_attempted(
        self, run_state: Any, loop: int, attempt: int, retry_index: int
    ) -> None:
        self._write_log_event(
            "llm.attempted",
            run_state,
            loop=loop,
            attempt=attempt,
            retry_index=retry_index,
        )

    def log_llm_responded(self, run_state: Any, loop: int, output: Any) -> None:
        self._write_log_event("llm.responded", run_state, loop=loop, output=output)

    def log_llm_failed(
        self, run_state: Any, loop: int, attempt: int, error: Any
    ) -> None:
        self._write_log_event(
            "llm.failed", run_state, loop=loop, attempt=attempt, error=error
        )

    def log_llm_retry_scheduled(
        self, run_state: Any, loop: int, retry_count: int, error: Any
    ) -> None:
        self._write_log_event(
            "llm.retry_scheduled",
            run_state,
            loop=loop,
            retry_count=retry_count,
            error=error,
        )

    def log_tool_started(
        self,
        run_state: Any,
        loop: int,
        call: Any,
        arguments: Any,
        attempt: int,
        idempotency_key: str | None,
    ) -> None:
        self._write_log_event(
            "tool.started",
            run_state,
            loop=loop,
            attempt=attempt,
            call_id=call.call_id,
            tool=call.name,
            arguments=arguments,
            idempotency_key=idempotency_key,
        )

    def log_tool_denied(
        self, run_state: Any, loop: int, call: Any, arguments: Any, loaded_skills: Any
    ) -> None:
        self._write_log_event(
            "tool.denied",
            run_state,
            loop=loop,
            call_id=call.call_id,
            tool=call.name,
            arguments=arguments,
            loaded_skills=list(loaded_skills),
            error="tool_not_allowed",
        )

    def log_tool_failed(
        self, run_state: Any, loop: int, call: Any, result: Any, error: Any
    ) -> None:
        self._write_log_event(
            "tool.failed",
            run_state,
            loop=loop,
            call_id=call.call_id,
            tool=call.name,
            arguments=call.arguments,
            result=result,
            error=error,
        )

    def log_tool_retry_scheduled(
        self, run_state: Any, loop: int, call: Any, retry_count: int, error: Any
    ) -> None:
        self._write_log_event(
            "tool.retry_scheduled",
            run_state,
            loop=loop,
            call_id=call.call_id,
            tool=call.name,
            retry_count=retry_count,
            error=error,
        )

    def log_tool_finished(
        self,
        run_state: Any,
        loop: int,
        action: Any,
        *,
        context_compaction: Any,
    ) -> None:
        event = "tool.completed" if action.status.value == "completed" else "tool.failed"
        self._write_log_event(
            event,
            run_state,
            loop=loop,
            action=action,
            context_compaction=context_compaction,
        )

    def log_tool_skipped(self, run_state: Any, loop: int, action: Any) -> None:
        self._write_log_event("tool.skipped", run_state, loop=loop, action=action)

    def log_final_answer(self, run_state: Any, content: str) -> None:
        self._write_log_event("run.final_answer", run_state, role="assistant", content=content)

    def log_run_completed(self, run_state: Any) -> None:
        self._write_log_event("run.completed", run_state, run_state=run_state.to_dict())

    def log_run_stopped(self, run_state: Any, final_answer: str) -> None:
        self._write_log_event(
            "run.stopped",
            run_state,
            final_answer=final_answer,
            run_state=run_state.to_dict(),
        )


events = EventLogger()
