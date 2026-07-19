from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from app.context.models import (
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.repository import JsonlConversationRepository
from app.domains.travel.repository import TravelRepository
from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryWriteContext
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryService
from app.planning.models import PlanCommand, PlanCommandAction
from app.recovery.models import RecoveryOutputMode
from app.recovery.runtime import build_recovery_runtime
from app.runtime.bootstrap import build_runtime_service
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.models import ConfirmedAction


@unittest.skipUnless(
    os.environ.get("LIFEOPS_RUN_FULL_LIVE_E2E") == "1",
    "Set LIFEOPS_RUN_FULL_LIVE_E2E=1 to call the configured LLM and live providers.",
)
class LiveUserE2ETest(unittest.TestCase):
    def test_01_real_research_mcp_direct_is_read_only_and_observable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "research")
            request = env.request(
                "Use the research skill and call research.search_papers exactly once "
                "to search public Hugging Face papers for agent runtime. This is one "
                "read-only lookup: return paper titles and canonical links. Do not "
                "create an execution preview or persist anything.",
                "research",
            )
            runtime = build_runtime_service(env.config_path)
            try:
                result = runtime.handle(request)
            finally:
                runtime.close()

            self.assertEqual(
                result.status,
                RuntimeStatus.OK,
                msg=_result_debug(result, env),
            )
            self.assertIn(
                "huggingface.co/papers/",
                result.message.lower(),
                msg=_result_debug(result, env),
            )
            events = env.events()
            self.assertEqual(
                _tool_names(events, "tool.call.requested"),
                ("research.search_papers",),
            )
            self.assertEqual(
                _tool_names(events, "tool.call.completed"),
                ("research.search_papers",),
            )
            self.assertEqual(_tool_names(events, "tool.call.failed"), ())
            self.assertEqual(env.count("plan_runs"), 0)
            self.assertEqual(env.count("research_sources"), 0)
            self.assertEqual(env.count("trips"), 0)
            self.assertEqual(env.count("memory_index"), 0)
            self.assertTrue(env.llm_rows())
            self.assertTrue(env.application_logs())
            trace_id = _assert_shared_trace(
                self,
                env,
                request.run_id,
                required_span_kinds={"RUNTIME", "LLM", "TOOL", "GUARDRAIL"},
            )
            _assert_feedback_and_recovery(
                self, env, request.run_id, trace_id, expected_path="direct"
            )

    def test_02_real_plan_preview_executes_research_then_saved_trip_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "plan")
            confirmations = _ScriptedUserConfirmationProvider(
                ("travel.create_trip",)
            )
            runtime = build_runtime_service(
                env.config_path,
                confirmation_provider=confirmations,
            )
            try:
                create_result = runtime.handle(
                    env.request(
                        "Use the travel skill and call travel.create_trip exactly "
                        "once with title LIVE-TRIP-PLAN-7319. After the successful "
                        "Tool observation, answer immediately.",
                        "create_trip",
                    )
                )
                self.assertEqual(
                    create_result.status,
                    RuntimeStatus.OK,
                    msg=_result_debug(create_result, env),
                )
                trip_id = env.scalar(
                    "SELECT id FROM trips WHERE title = ?",
                    ("LIVE-TRIP-PLAN-7319",),
                )
                goal = (
                    "Use the research and travel skills. This is a multi-step "
                    "read-only request with two dependent goals and must return an "
                    "execution preview before any Tool runs. First call "
                    "research.search_papers exactly once for AI itinerary planning. "
                    f"Then call travel.get_trip exactly once for trip_id {trip_id}. "
                    "Return a combined answer. Persistence is out of scope."
                )
                preview = runtime.handle(env.request(goal, "preview"))
                self.assertEqual(
                    preview.status,
                    RuntimeStatus.REQUIRES_CONFIRMATION,
                    msg=_result_debug(preview, env),
                )
                self.assertEqual(preview.tool_result["type"], "plan_preview")
                before_confirm_tools = len(
                    _tool_names(env.events(), "tool.call.requested")
                )
                command = PlanCommand(
                    "command_live_plan",
                    preview.tool_result["plan_id"],
                    env.session_id,
                    preview.tool_result["revision"],
                    PlanCommandAction.CONFIRM,
                )
                result = runtime.handle_plan_command(
                    command,
                    env.request(goal, "confirm"),
                )
            finally:
                runtime.close()

            self.assertEqual(
                result.status,
                RuntimeStatus.OK,
                msg=_result_debug(result, env),
            )
            self.assertEqual(result.tool_result["plan_status"], "completed")
            requested = _tool_names(env.events(), "tool.call.requested")
            self.assertEqual(before_confirm_tools, 1)
            self.assertIn("travel.create_trip", requested)
            self.assertIn("research.search_papers", requested)
            self.assertIn("travel.get_trip", requested)
            self.assertEqual(confirmations.tool_names, ["travel.create_trip"])
            self.assertEqual(env.count("trips"), 1)
            self.assertEqual(env.count("research_sources"), 0)
            self.assertEqual(env.count("travel_itineraries"), 0)
            self.assertEqual(
                env.scalar(
                    "SELECT status FROM plan_runs WHERE id = ?",
                    (preview.tool_result["plan_id"],),
                ),
                "completed",
            )
            preview_trace_id = _assert_shared_trace(
                self,
                env,
                preview.run_id,
                required_span_kinds={"RUNTIME", "PLANNER", "LLM"},
            )
            confirm_trace_id = _assert_shared_trace(
                self,
                env,
                result.run_id,
                required_span_kinds={"RUNTIME", "PLANNER", "EXECUTOR", "LLM", "TOOL"},
            )
            _assert_feedback_and_recovery(
                self,
                env,
                result.run_id,
                confirm_trace_id,
                expected_path="planning",
            )
            continuation_links = [
                row
                for row in env.trace_rows()
                if row["record_type"] == "span_link"
                and row["source_trace_id"] == confirm_trace_id
                and row["link_type"] == "plan_continuation"
            ]
            self.assertEqual(len(continuation_links), 1)
            self.assertEqual(
                continuation_links[0]["target_trace_id"],
                preview_trace_id,
            )

    def test_03_real_context_summary_and_restart_preserve_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "context")
            old_marker = "CTX-ORBIT-7319"
            recent_marker = "CTX-LANTERN-2085"
            _seed_long_conversation(env, old_marker, recent_marker)

            first_runtime = build_runtime_service(env.config_path)
            try:
                first = first_runtime.handle(
                    env.request(
                        "Return the exact old marker and exact recent marker from "
                        "this session. Do not use any Tool.",
                        "context_first",
                    )
                )
            finally:
                first_runtime.close()
            self.assertEqual(
                first.status,
                RuntimeStatus.OK,
                msg=_result_debug(first, env),
            )
            self.assertIn(old_marker, _normalized_text(first.message))
            self.assertIn(recent_marker, _normalized_text(first.message))
            summary = JsonlConversationRepository(
                env.root / "conversations"
            ).load_latest_valid_summary(env.session_id)
            self.assertIsNotNone(summary)
            self.assertIn(old_marker, summary.content)

            second_runtime = build_runtime_service(env.config_path)
            try:
                second = second_runtime.handle(
                    env.request(
                        "After the runtime restart, repeat the exact old marker and "
                        "the exact recent marker. Do not use any Tool.",
                        "context_restart",
                    )
                )
            finally:
                second_runtime.close()

            self.assertEqual(
                second.status,
                RuntimeStatus.OK,
                msg=_result_debug(second, env),
            )
            self.assertIn(old_marker, _normalized_text(second.message))
            self.assertIn(recent_marker, _normalized_text(second.message))
            self.assertEqual(env.count("memory_index"), 0)
            self.assertEqual(env.count("plan_runs"), 0)
            self.assertEqual(_tool_names(env.events(), "tool.call.requested"), ())

    def test_04a_real_memory_save_is_single_write_and_durable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "memory")
            memory_root = env.root / "memory"
            memory_root.mkdir(parents=True)
            memory_marker = "MEM-NOVA-4821"

            confirmations = _ScriptedUserConfirmationProvider(("memory.save",))
            runtime = build_runtime_service(
                env.config_path,
                confirmation_provider=confirmations,
            )
            try:
                saved = runtime.handle(
                    env.request(
                        "Please remember this exact long-term preference for future "
                        "sessions: my durable focus window is 07:30, code "
                        f"{memory_marker}.",
                        "save",
                    )
                )
            finally:
                runtime.close()

            self.assertEqual(saved.status, RuntimeStatus.OK, _result_debug(saved, env))
            self.assertEqual(confirmations.tool_names, ["memory.save"])
            self.assertEqual(confirmations.approved_tool_names, ["memory.save"])
            self.assertEqual(env.count("memory_index"), 1)
            row = env.rows(
                "SELECT status, relative_path, content_hash, confirmation_ref, "
                "evidence_ref FROM memory_index"
            )[0]
            self.assertEqual(row[0], "active")
            document_path = memory_root / row[1]
            self.assertTrue(document_path.is_file())
            document_bytes = document_path.read_bytes()
            self.assertIn(memory_marker, document_bytes.decode("utf-8"))
            self.assertEqual(hashlib.sha256(document_bytes).hexdigest(), row[2])
            self.assertTrue(row[3].startswith("confirmation://"))
            self.assertTrue(row[4].startswith("tool-evidence://"))

    def test_04b_real_profile_and_seeded_memory_restart_recall_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "memory_recall")
            memory_root = env.root / "memory"
            memory_root.mkdir(parents=True)
            profile_marker = "PROFILE-CEDAR-7314"
            memory_marker = "MEM-NOVA-4821"
            (memory_root / "profile.md").write_text(
                f"My profile marker is {profile_marker}; I avoid peanuts.",
                encoding="utf-8",
            )
            _seed_verified_memory(env, memory_marker)

            denied = _ScriptedUserConfirmationProvider(())
            restarted = build_runtime_service(
                env.config_path,
                confirmation_provider=denied,
            )
            try:
                recalled = restarted.handle(
                    env.request(
                        "Read only: what exact profile marker and food avoidance do I "
                        "have, and what durable focus window and code are stored for "
                        "me? Include both exact codes and do not change stored data.",
                        "restart_read",
                        session_id="session_live_memory_restart",
                    )
                )
            finally:
                restarted.close()

            self.assertEqual(recalled.status, RuntimeStatus.OK, _result_debug(recalled, env))
            recalled_text = _normalized_text(recalled.message)
            self.assertIn(profile_marker, recalled_text)
            self.assertIn(memory_marker, recalled_text)
            self.assertIn("07:30", recalled_text)
            self.assertEqual(env.count("memory_index"), 1)
            self.assertEqual(denied.tool_names, [])
            self.assertEqual(_tool_names(env.events(), "tool.call.requested"), ())

    def test_05a_real_travel_provider_failure_is_reported_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "safety")
            runtime = build_runtime_service(env.config_path)
            try:
                unavailable_request = env.request(
                        "Use the travel skill and call travel.search_places exactly "
                        "once for destination Testville and query museums. If the "
                        "provider is unavailable, report that honestly and stop.",
                        "unavailable",
                    )
                unavailable = runtime.handle(unavailable_request)
                self.assertEqual(
                    unavailable.status,
                    RuntimeStatus.OK,
                    _result_debug(unavailable, env),
                )
                vague = runtime.handle(env.request("计划一下", "vague"))
            finally:
                runtime.close()

            self.assertEqual(vague.status, RuntimeStatus.REQUIRES_CONFIRMATION)
            self.assertEqual(env.count("plan_runs"), 0)
            self.assertEqual(env.count("travel_itineraries"), 0)
            events = env.events()
            self.assertIn(
                "travel.search_places",
                _tool_names(events, "tool.call.failed"),
                _result_debug(unavailable, env),
            )
            failure_trace_id = _assert_shared_trace(
                self,
                env,
                unavailable_request.run_id,
                required_span_kinds={"RUNTIME", "LLM", "TOOL", "GUARDRAIL"},
            )
            _assert_feedback_and_recovery(
                self,
                env,
                unavailable_request.run_id,
                failure_trace_id,
                expected_path="direct",
                expected_statuses={"failed", "partial"},
            )

    def test_05b_real_archive_confirmation_denial_keeps_trip_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "policy_stop")
            trip_id = _seed_trip(env, "LIVE-TRIP-SAFETY-4826")
            denied = _ScriptedUserConfirmationProvider(())
            denied_runtime = build_runtime_service(
                env.config_path,
                confirmation_provider=denied,
            )
            try:
                denied_result = denied_runtime.handle(
                    env.request(
                        "Use the travel skill and call travel.archive_trip exactly once "
                        f"for trip_id {trip_id}, expected_version 1. Stop after the "
                        "Tool result.",
                        "deny_archive",
                    )
                )
            finally:
                denied_runtime.close()
            self.assertNotEqual(
                denied_result.status,
                RuntimeStatus.OK,
                _result_debug(denied_result, env),
            )
            self.assertEqual(
                env.scalar("SELECT status FROM trips WHERE id = ?", (trip_id,)),
                "active",
            )

    def test_06_real_planning_partial_feedback_and_restart_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = _LiveEnvironment(Path(tmpdir), "planning_partial")
            runtime = build_runtime_service(env.config_path)
            try:
                goal = (
                    "Use the research and travel skills for two dependent steps and "
                    "return an execution preview before any Tool runs. First call "
                    "research.search_papers exactly once for agent runtime. Then call "
                    "travel.search_places exactly once for "
                    "destination Testville and query museums. The travel provider "
                    "may be unavailable; preserve the completed research result and "
                    "report the failed later step honestly. Do not persist results."
                )
                preview = runtime.handle(env.request(goal, "preview"))
                self.assertEqual(
                    preview.status,
                    RuntimeStatus.REQUIRES_CONFIRMATION,
                    _result_debug(preview, env),
                )
                confirm_request = env.request(goal, "confirm")
                result = runtime.handle_plan_command(
                    PlanCommand(
                        "command_live_partial",
                        preview.tool_result["plan_id"],
                        env.session_id,
                        preview.tool_result["revision"],
                        PlanCommandAction.CONFIRM,
                    ),
                    confirm_request,
                )
            finally:
                runtime.close()

            trace_id = _assert_shared_trace(
                self,
                env,
                confirm_request.run_id,
                required_span_kinds={"RUNTIME", "PLANNER", "EXECUTOR", "LLM", "TOOL"},
            )
            _assert_feedback_and_recovery(
                self,
                env,
                confirm_request.run_id,
                trace_id,
                expected_path="planning",
                expected_statuses={"partial"},
            )
            outcomes = {
                row[0]
                for row in env.rows(
                    """SELECT outcome FROM execution_feedback_plan_steps
                       WHERE feedback_id = (
                           SELECT id FROM execution_feedback WHERE run_id = ?
                       )""",
                    (confirm_request.run_id,),
                )
            }
            self.assertIn("completed", outcomes)
            self.assertTrue(
                outcomes.intersection({"failed", "not_run"}),
                f"unexpected plan-step outcomes: {sorted(outcomes)}",
            )


class _ScriptedUserConfirmationProvider:
    def __init__(self, approved_sequence: tuple[str, ...]) -> None:
        self.approved_sequence = approved_sequence
        self._next_approval = 0
        self.tool_names: list[str] = []
        self.approved_tool_names: list[str] = []
        self._approved_run_ids: set[str] = set()

    def confirm(self, run_id, call, tool_definition):
        del tool_definition
        self.tool_names.append(call.tool_name)
        if run_id in self._approved_run_ids:
            return None
        if self._next_approval >= len(self.approved_sequence):
            return None
        if call.tool_name != self.approved_sequence[self._next_approval]:
            return None
        self._next_approval += 1
        self._approved_run_ids.add(run_id)
        self.approved_tool_names.append(call.tool_name)
        return ConfirmedAction.for_call(
            run_id,
            call,
            expires_at="2100-01-01T00:00:00+00:00",
        )


class _LiveEnvironment:
    def __init__(self, root: Path, case_id: str) -> None:
        self.root = root
        self.case_id = case_id
        self.database_path = root / "lifeops.db"
        self.log_root = root / "logs"
        self.config_path = root / "config.json"
        self.session_id = f"session_live_{case_id}"
        self._request_number = 0
        self.config_path.write_text(
            json.dumps(
                {
                    "database": {"path": str(self.database_path)},
                    "logs": {"root": str(self.log_root)},
                    "skills": {"root": str(Path("app/skills").resolve())},
                }
            ),
            encoding="utf-8",
        )

    def request(
        self,
        text: str,
        suffix: str,
        *,
        session_id: str | None = None,
    ) -> RuntimeRequest:
        self._request_number += 1
        effective_session_id = session_id or self.session_id
        return RuntimeRequest(
            text,
            effective_session_id,
            f"turn_live_{self.case_id}_{self._request_number}_{suffix}",
            f"run_live_{self.case_id}_{self._request_number}_{suffix}",
        )

    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}"))

    def scalar(self, sql: str, params: tuple = ()):
        conn = sqlite3.connect(self.database_path)
        try:
            row = conn.execute(sql, params).fetchone()
        finally:
            conn.close()
        if row is None:
            raise AssertionError(f"query returned no row: {sql}")
        return row[0]

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        conn = sqlite3.connect(self.database_path)
        try:
            return list(conn.execute(sql, params).fetchall())
        finally:
            conn.close()

    def events(self) -> list[dict]:
        return _read_jsonl(self.log_root, "events.jsonl")

    def llm_rows(self) -> list[dict]:
        return _read_jsonl(self.log_root, "llm.jsonl")

    def trace_rows(self) -> list[dict]:
        return _read_jsonl(self.log_root, "traces.jsonl")

    def application_logs(self) -> list[Path]:
        return list(self.log_root.rglob("application.log"))


def _seed_long_conversation(
    env: _LiveEnvironment,
    old_marker: str,
    recent_marker: str,
) -> str:
    repository = JsonlConversationRepository(env.root / "conversations")
    contents = (
        f"My old exact session marker is {old_marker}.",
        "Old marker acknowledged.",
        f"Keep {old_marker} available for a later context question.",
        "I will keep the old marker in session context.",
        "My stable preference is concise Chinese answers.",
        "Preference acknowledged.",
        "This is an ordinary filler turn about runtime testing.",
        "Filler turn acknowledged.",
        "Another filler turn keeps the session long enough for compaction.",
        "Second filler turn acknowledged.",
        f"My recent exact marker is {recent_marker}.",
        "Recent marker acknowledged.",
    )
    for index, content in enumerate(contents, start=1):
        user = index % 2 == 1
        repository.append_turn(
            ConversationTurn(
                1,
                env.session_id,
                f"seed_turn_{index}",
                index,
                ConversationRole.USER if user else ConversationRole.ASSISTANT,
                (
                    ConversationTurnKind.NATURAL_INPUT
                    if user
                    else ConversationTurnKind.FINAL_ANSWER
                ),
                content,
                f"seed_run_{index}",
                f"2026-07-16T00:{index:02d}:00+00:00",
            )
        )


def _seed_verified_memory(env: _LiveEnvironment, marker: str) -> None:
    conn = connect_sqlite(env.database_path)
    try:
        migrate(conn)
        MemoryService(
            SqliteMemoryRepository(conn),
            MemoryDocumentStore(env.root / "memory"),
        ).save_confirmed(
            f"My durable focus window is 07:30, code {marker}.",
            ("focus-window",),
            MemoryWriteContext(
                "session_fixture_memory",
                "turn_fixture_memory",
                "run_fixture_memory",
                "call_fixture_memory",
                "confirmation://fixture/memory",
                "tool-evidence://fixture/memory",
            ),
        )
    finally:
        conn.close()


def _seed_trip(env: _LiveEnvironment, title: str) -> str:
    conn = connect_sqlite(env.database_path)
    try:
        migrate(conn)
        return TravelRepository(conn).create_trip(title).trip_id
    finally:
        conn.close()


def _read_jsonl(root: Path, name: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(root.rglob(name)):
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


def _normalized_text(value: str) -> str:
    return value.translate(
        str.maketrans(
            {
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2212": "-",
            }
        )
    )


def _tool_names(events: list[dict], event_type: str) -> tuple[str, ...]:
    return tuple(
        row["payload"]["tool_name"]
        for row in events
        if row["event_type"] == event_type
    )


def _assert_shared_trace(
    test: unittest.TestCase,
    env: _LiveEnvironment,
    run_id: str,
    *,
    required_span_kinds: set[str],
) -> None:
    rows = env.trace_rows()
    trace_records = [
        row
        for row in rows
        if row["record_type"] == "trace" and row["run_id"] == run_id
    ]
    test.assertEqual(len(trace_records), 1)
    trace_id = trace_records[0]["trace_id"]
    spans = [
        row
        for row in rows
        if row["record_type"] == "span" and row["trace_id"] == trace_id
    ]
    test.assertTrue(required_span_kinds.issubset({row["lifeops_span_kind"] for row in spans}))
    llm_spans = {
        row["span_id"]: row for row in spans if row["lifeops_span_kind"] == "LLM"
    }
    test.assertTrue(llm_spans)
    test.assertTrue(
        all(
            span["attributes"].get("llm.provider")
            and span["attributes"].get("llm.model")
            for span in llm_spans.values()
        )
    )
    usage_by_sequence = {
        row["seq"]: row["response"].get("usage", {})
        for row in env.llm_rows()
        if row["run_id"] == run_id and isinstance(row.get("response"), dict)
    }
    for span in llm_spans.values():
        sequence = span["attributes"]["llm.interaction.sequence"]
        usage = usage_by_sequence.get(sequence, {})
        if usage:
            test.assertEqual(
                span["attributes"].get("llm.usage.total_tokens"),
                usage.get("total_tokens"),
            )
    llm_artifacts = [
        row
        for row in rows
        if row["record_type"] == "artifact_reference"
        and row["trace_id"] == trace_id
        and row["artifact_type"] == "llm_interaction"
    ]
    test.assertEqual(len(llm_artifacts), len(llm_spans))
    test.assertTrue(
        all(
            row["span_id"] in llm_spans
            and row["sensitivity"] == "sensitive"
            and row["safe_reference"].startswith("llm.jsonl#id=logllm_")
            for row in llm_artifacts
        )
    )
    return trace_id


def _assert_feedback_and_recovery(
    test: unittest.TestCase,
    env: _LiveEnvironment,
    run_id: str,
    trace_id: str,
    *,
    expected_path: str,
    expected_statuses: set[str] | None = None,
) -> None:
    feedback_rows = env.rows(
        """SELECT trace_id, path, overall_status, validation_claim_status
           FROM execution_feedback WHERE run_id = ?""",
        (run_id,),
    )
    test.assertEqual(len(feedback_rows), 1)
    feedback_trace_id, path, status, claim_status = feedback_rows[0]
    test.assertEqual(feedback_trace_id, trace_id)
    test.assertEqual(path, expected_path)
    test.assertIn(claim_status, {"valid", "invalid"})
    if expected_statuses is not None:
        test.assertIn(status, expected_statuses)

    source_artifacts = [
        row
        for row in env.trace_rows()
        if row["record_type"] == "artifact_reference"
        and row["trace_id"] == trace_id
        and row["artifact_type"] == "execution_feedback"
    ]
    test.assertEqual(len(source_artifacts), 1)
    test.assertEqual(source_artifacts[0]["sensitivity"], "internal")

    recovery = build_recovery_runtime(env.config_path)
    try:
        result = recovery.explain(env.session_id, run_id)
    finally:
        recovery.close()
    test.assertEqual(result.context.source_run_id, run_id)
    test.assertEqual(result.context.source_trace_id, trace_id)
    test.assertEqual(result.output_mode, RecoveryOutputMode.DETERMINISTIC)

    rows = env.trace_rows()
    links = [
        row
        for row in rows
        if row["record_type"] == "span_link"
        and row["link_type"] == "recovery_of"
        and row["target_trace_id"] == trace_id
    ]
    test.assertEqual(len(links), 1)
    recovery_trace_id = links[0]["source_trace_id"]
    recovery_kinds = {
        row["lifeops_span_kind"]
        for row in rows
        if row["record_type"] == "span" and row["trace_id"] == recovery_trace_id
    }
    test.assertEqual(recovery_kinds, {"RUNTIME", "RECOVERY"})
    recovery_artifacts = [
        row
        for row in rows
        if row["record_type"] == "artifact_reference"
        and row["trace_id"] == recovery_trace_id
        and row["artifact_type"] == "recovery_context"
    ]
    test.assertEqual(len(recovery_artifacts), 1)


def _result_debug(result, env: _LiveEnvironment) -> str:
    events = env.events() if env.log_root.exists() else []
    llm_rows = env.llm_rows() if env.log_root.exists() else []
    llm_skeleton = tuple(
        (
            row.get("request", {}).get("operation"),
            row.get("status"),
            row.get("error_code"),
            row.get("response"),
        )
        for row in llm_rows
    )
    feedback = (
        env.rows(
            """SELECT overall_status, validation_claim_status,
                      validation_output_mode, validation_reason_codes_json,
                      validation_accepted_claim_ids_json
               FROM execution_feedback WHERE run_id = ?""",
            (result.run_id,),
        )
        if env.database_path.exists()
        else []
    )
    return (
        f"status={result.status.value} error={result.error_code} "
        f"tools={_tool_names(events, 'tool.call.requested')} "
        f"failed={_tool_names(events, 'tool.call.failed')} "
        f"llm={llm_skeleton} feedback={feedback}"
    )


if __name__ == "__main__":
    unittest.main()
