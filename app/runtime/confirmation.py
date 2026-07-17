"""Interactive adapters for request-local Tool action confirmation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json

from app.tools.models import (
    ConfirmedAction,
    ToolCall,
    ToolDefinition,
    ToolEffect,
)


class CliActionConfirmationProvider:
    """Ask the local CLI user to approve one exact WRITE ToolCall."""

    def __init__(
        self,
        *,
        input_reader: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise ValueError("ttl must be a positive timedelta.")
        self._input_reader = input_reader or input
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl

    def confirm(
        self,
        run_id: str,
        call: ToolCall,
        tool_definition: ToolDefinition,
    ) -> ConfirmedAction | None:
        """Return a short-lived exact confirmation only for an explicit yes."""

        if tool_definition.effect != ToolEffect.WRITE:
            return None
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            return None
        arguments = json.dumps(
            call.arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        prompt = (
            "\nWRITE Tool confirmation required\n"
            f"tool: {call.tool_name}\n"
            f"effect: {tool_definition.effect.value}\n"
            f"risk: {tool_definition.risk.value}\n"
            f"arguments: {arguments}\n"
            "Approve this exact action? [y/N]: "
        )
        try:
            answer = self._input_reader(prompt)
        except (EOFError, KeyboardInterrupt, OSError):
            return None
        if not isinstance(answer, str) or answer.strip().lower() not in {"y", "yes"}:
            return None
        return ConfirmedAction.for_call(
            run_id,
            call,
            expires_at=(now.astimezone(UTC) + self._ttl).isoformat(),
        )
