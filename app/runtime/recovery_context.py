"""Request-local Recovery context selection and formatting."""

import re
from dataclasses import dataclass
from typing import Any

from app.runtime.recovery_store import (
    RECOVERABLE_RUN_STATUSES,
    RunRecordStore,
)
from app.runtime.recovery_types import PersistentActionRecord, RunRecord
from app.tasks.task_context import TaskContextResult


RECOVERY_CONTEXT_TITLE = "Recent recovery context (read-only)"
RECOVERY_CANDIDATES_TITLE = "Recovery candidates (read-only)"


@dataclass(frozen=True)
class RecoveryContextResult:
    """Recovery context selected for one model request."""

    runs: tuple[RunRecord, ...]
    reason: str | None
    ambiguous: bool = False

    @property
    def injected(self) -> bool:
        return bool(self.runs)

    def message(self) -> dict[str, str] | None:
        if not self.runs:
            return None
        if self.ambiguous:
            return {"role": "system", "content": _format_candidates(self.runs)}
        return {"role": "system", "content": _format_run(self.runs[0])}

    def report(self, message: dict[str, str] | None) -> dict[str, Any]:
        return {
            "recovery_context_injected": message is not None,
            "recovery_context_reason": self.reason,
            "recovery_context_ambiguous": self.ambiguous,
            "recovery_context_run_ids": [run.run_id for run in self.runs],
            "recovery_context_statuses": [run.status for run in self.runs],
            "recovery_context_task_ids": [run.task_id for run in self.runs],
            "recovery_context_chars": len(message["content"]) if message else 0,
        }


class RecoveryContextBuilder:
    """Build read-only Recovery Context from persisted run records."""

    def __init__(self, store: RunRecordStore | None = None) -> None:
        self.store = store or RunRecordStore()

    def build(
        self,
        user_input: str,
        *,
        task_context: TaskContextResult | None = None,
    ) -> RecoveryContextResult:
        text = user_input.strip()
        recoverable_runs = [
            run
            for run in self.store.list_recent_runs(limit=20)
            if run.status in RECOVERABLE_RUN_STATUSES
        ]
        if not recoverable_runs:
            return RecoveryContextResult(runs=(), reason="no_recoverable_runs")

        task_ids = _task_ids_from_context(task_context)
        if task_ids:
            related_runs = [
                run for run in recoverable_runs if run.task_id in task_ids
            ]
            if related_runs:
                if len(related_runs) == 1:
                    return RecoveryContextResult(
                        runs=(related_runs[0],),
                        reason="task_related_recoverable_run",
                    )
                return RecoveryContextResult(
                    runs=tuple(related_runs[:5]),
                    reason="multiple_task_related_recoverable_runs",
                    ambiguous=True,
                )

        if not _has_recovery_cue(text):
            return RecoveryContextResult(runs=(), reason="no_recovery_cue")

        if len(recoverable_runs) == 1:
            return RecoveryContextResult(
                runs=(recoverable_runs[0],),
                reason="latest_recoverable_run",
            )
        return RecoveryContextResult(
            runs=tuple(recoverable_runs[:5]),
            reason="multiple_recoverable_runs",
            ambiguous=True,
        )


def _task_ids_from_context(task_context: TaskContextResult | None) -> set[str]:
    if task_context is None or task_context.ambiguous:
        return set()
    return {task.id for task in task_context.tasks}


def _has_recovery_cue(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"继续.{0,12}(?:刚才|上次|之前)"
            r"|恢复.{0,12}(?:刚才|上次|之前)"
            r"|上次.{0,12}(?:失败|做到|做了|停在|执行)"
            r"|刚才.{0,12}(?:失败|做到|做了|停在|执行)"
            r"|where did .{0,24}(?:fail|stop)"
            r"|continue .{0,16}(?:previous|last)"
            r"|resume .{0,16}(?:previous|last)",
            lowered,
        )
    )


def _format_run(run: RunRecord) -> str:
    lines = [
        f"{RECOVERY_CONTEXT_TITLE}:",
        f"- run_id: {run.run_id}",
        f"- status: {run.status}",
        f"- stop_reason: {run.stop_reason or 'none'}",
        f"- task_id: {run.task_id or 'none'}",
        f"- user_input_summary: {run.user_input_summary}",
        f"- action_count: {run.action_count}",
        f"- last successful action: {_format_action(run.last_successful_action)}",
        f"- last failed action: {_format_action(run.last_failed_action)}",
        "",
        "Recovery rules:",
        "- This context is read-only and request-local.",
        "- Do not replay tools automatically.",
        "- Re-check current user authorization before any WRITE.",
        "- Ask the user when the next action is ambiguous or risky.",
        "- Do not claim recovery completed unless this turn has a successful Tool Observation.",
    ]
    return "\n".join(lines)


def _format_candidates(runs: tuple[RunRecord, ...]) -> str:
    lines = [
        f"{RECOVERY_CANDIDATES_TITLE}:",
        "Multiple recoverable runs match the user's request. Ask the user to choose one by run_id before acting.",
    ]
    for run in runs[:5]:
        lines.append(
            f"- run_id: {run.run_id}; status: {run.status}; "
            f"stop_reason: {run.stop_reason or 'none'}; "
            f"task_id: {run.task_id or 'none'}; "
            f"last_successful_action: {_action_name(run.last_successful_action)}; "
            f"last_failed_action: {_action_name(run.last_failed_action)}"
        )
    lines.extend(
        [
            "",
            "Recovery rules:",
            "- Do not replay tools automatically.",
            "- Re-check current user authorization before any WRITE.",
            "- Ask the user to choose one run_id before continuing.",
        ]
    )
    return "\n".join(lines)


def _format_action(action: PersistentActionRecord | None) -> str:
    if action is None:
        return "none"
    summary = action.result_summary if action.status == "completed" else action.error_summary
    return (
        f"[{action.action_id}] {action.tool_name} "
        f"({action.status}, {action.effect}); "
        f"call_id={action.call_id}; summary={summary or 'none'}"
    )


def _action_name(action: PersistentActionRecord | None) -> str:
    return action.tool_name if action is not None else "none"
