"""Canonical SQLite schema definition."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    sql: str


SCHEMA_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""

V1_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_records (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    user_input_hash TEXT,
    summary TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    call_type TEXT NOT NULL,
    status TEXT NOT NULL,
    input_json TEXT,
    output_json TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES run_records(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id
ON tool_calls(run_id);

CREATE TABLE IF NOT EXISTS research_topics (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_sources (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_sources_source_key
ON research_sources(source_key);

CREATE TABLE IF NOT EXISTS research_source_snapshots (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    fetched_at TEXT NOT NULL,
    published_at TEXT,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES research_sources(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_research_source_snapshots_source_id
ON research_source_snapshots(source_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS research_notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_briefs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_brief_sources (
    brief_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (brief_id, source_id),
    UNIQUE (brief_id, position),
    FOREIGN KEY (brief_id) REFERENCES research_briefs(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES research_sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (snapshot_id) REFERENCES research_source_snapshots(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS research_links (
    id TEXT PRIMARY KEY,
    from_kind TEXT NOT NULL CHECK (from_kind IN ('topic', 'source', 'note', 'brief')),
    from_id TEXT NOT NULL,
    to_kind TEXT NOT NULL CHECK (to_kind IN ('topic', 'source', 'note', 'brief')),
    to_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (from_kind, from_id, to_kind, to_id, relation),
    CHECK (from_kind <> to_kind OR from_id <> to_id)
);

CREATE INDEX IF NOT EXISTS idx_research_links_from_item
ON research_links(from_kind, from_id);

CREATE INDEX IF NOT EXISTS idx_research_links_to_item
ON research_links(to_kind, to_id);

CREATE TABLE IF NOT EXISTS research_revisions (
    id TEXT PRIMARY KEY,
    item_kind TEXT NOT NULL CHECK (item_kind IN ('topic', 'source', 'note', 'brief')),
    item_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (item_kind, item_id, version)
);

CREATE INDEX IF NOT EXISTS idx_research_revisions_item
ON research_revisions(item_kind, item_id, version);

CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
    version INTEGER NOT NULL CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    CHECK (
        (status = 'active' AND archived_at IS NULL)
        OR (status = 'archived' AND archived_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS travel_constraints (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'budget', 'date', 'destination', 'document', 'lodging',
            'other', 'transport', 'traveler_count'
        )
    ),
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (trip_id, kind, value),
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_travel_constraints_trip
ON travel_constraints(trip_id, kind, created_at, id);

CREATE TABLE IF NOT EXISTS travel_itineraries (
    id TEXT PRIMARY KEY,
    destination TEXT NOT NULL,
    transport TEXT NOT NULL,
    lodging TEXT NOT NULL,
    summary TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    trip_id TEXT REFERENCES trips(id) ON DELETE RESTRICT,
    draft_id TEXT,
    idempotency_key TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_travel_itineraries_destination
ON travel_itineraries(destination);

CREATE UNIQUE INDEX IF NOT EXISTS idx_travel_itineraries_idempotency_key
ON travel_itineraries(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_travel_itineraries_trip
ON travel_itineraries(trip_id, created_at, id);

CREATE TABLE IF NOT EXISTS travel_itinerary_items (
    id TEXT PRIMARY KEY,
    itinerary_id TEXT NOT NULL,
    day_number INTEGER NOT NULL CHECK (day_number >= 1),
    title TEXT NOT NULL,
    item_type TEXT NOT NULL,
    starts_at TEXT,
    ends_at TEXT,
    source_candidate_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    CHECK ((starts_at IS NULL) = (ends_at IS NULL)),
    FOREIGN KEY (itinerary_id) REFERENCES travel_itineraries(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_travel_itinerary_items_itinerary
ON travel_itinerary_items(itinerary_id, day_number, starts_at, id);

CREATE TABLE IF NOT EXISTS travel_decisions (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    itinerary_id TEXT,
    kind TEXT NOT NULL CHECK (
        kind IN ('calendar', 'destination', 'itinerary', 'lodging', 'place', 'transport')
    ),
    selected_candidate_ids_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    UNIQUE (itinerary_id, kind),
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY (itinerary_id) REFERENCES travel_itineraries(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_travel_decisions_trip
ON travel_decisions(trip_id, decided_at, id);

CREATE TABLE IF NOT EXISTS travel_knowledge_refs (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (trip_id, domain, item_kind, item_id),
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_travel_knowledge_refs_trip
ON travel_knowledge_refs(trip_id, created_at, id);
"""

V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'awaiting_confirmation', 'running', 'awaiting_replan_confirmation',
            'completed', 'stopped', 'failed', 'cancelled'
        )
    ),
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    replan_count INTEGER NOT NULL CHECK (replan_count >= 0),
    executor_steps_used INTEGER NOT NULL CHECK (executor_steps_used >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT,
    completed_at TEXT,
    last_error_code TEXT,
    last_command_id TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_plan_runs_session
ON plan_runs(session_id, created_at, id);

CREATE TABLE IF NOT EXISTS plan_steps (
    plan_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    step_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 1),
    objective TEXT NOT NULL,
    expected_outcome TEXT NOT NULL,
    dependency_step_ids_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'running', 'completed', 'goal_not_achieved',
            'stopped', 'failed', 'superseded', 'cancelled'
        )
    ),
    stop_reason TEXT,
    safe_result_summary TEXT,
    error_code TEXT,
    evidence_refs_json TEXT NOT NULL,
    executor_steps_used INTEGER NOT NULL CHECK (executor_steps_used >= 0),
    started_at TEXT,
    completed_at TEXT,
    PRIMARY KEY (plan_id, revision, step_id),
    UNIQUE (plan_id, revision, position),
    FOREIGN KEY (plan_id) REFERENCES plan_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_plan_steps_revision
ON plan_steps(plan_id, revision, position);

CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_steps_one_running
ON plan_steps(plan_id, revision)
WHERE status = 'running';
"""

V3_SCHEMA = """
ALTER TABLE plan_runs
ADD COLUMN confirmed_constraints_json TEXT NOT NULL DEFAULT '[]';
"""

V4_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_index (
    memory_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded', 'archived')),
    relative_path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    supersedes_memory_id TEXT,
    supersedes_version INTEGER,
    source_session_id TEXT NOT NULL,
    source_turn_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    source_tool_call_id TEXT NOT NULL,
    confirmation_ref TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    PRIMARY KEY (memory_id, version),
    CHECK ((supersedes_memory_id IS NULL) = (supersedes_version IS NULL)),
    CHECK (
        (version = 1 AND supersedes_memory_id IS NULL AND supersedes_version IS NULL)
        OR
        (version > 1 AND supersedes_memory_id = memory_id AND supersedes_version = version - 1)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_one_active
ON memory_index(memory_id)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_memory_status_updated
ON memory_index(status, updated_at, memory_id, version);

CREATE INDEX IF NOT EXISTS idx_memory_content_hash
ON memory_index(content_hash);
"""

V5_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_feedback (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    path TEXT NOT NULL CHECK (path IN ('direct', 'planning')),
    goal_summary TEXT NOT NULL,
    overall_status TEXT NOT NULL CHECK (
        overall_status IN (
            'completed', 'partial', 'failed', 'denied',
            'requires_confirmation', 'not_run'
        )
    ),
    stop_reason TEXT,
    error_code TEXT,
    executor_invocation_ids_json TEXT NOT NULL,
    plan_id TEXT,
    revision INTEGER CHECK (revision IS NULL OR revision >= 1),
    stop_step_id TEXT,
    validation_claim_status TEXT NOT NULL CHECK (
        validation_claim_status IN ('valid', 'invalid')
    ),
    validation_output_mode TEXT NOT NULL CHECK (
        validation_output_mode IN ('model', 'deterministic_fallback')
    ),
    validation_reason_codes_json TEXT NOT NULL,
    validation_accepted_claim_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (path = 'direct' AND plan_id IS NULL AND revision IS NULL AND stop_step_id IS NULL)
        OR
        (path = 'planning' AND plan_id IS NOT NULL AND revision IS NOT NULL)
    ),
    FOREIGN KEY (run_id) REFERENCES run_records(id) ON DELETE CASCADE,
    FOREIGN KEY (plan_id) REFERENCES plan_runs(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_execution_feedback_session_created
ON execution_feedback(session_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_execution_feedback_plan
ON execution_feedback(plan_id, revision);

CREATE TABLE IF NOT EXISTS execution_feedback_actions (
    feedback_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    executor_invocation_id TEXT NOT NULL,
    source_span_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_effect TEXT NOT NULL CHECK (
        tool_effect IN ('read', 'write', 'external_read')
    ),
    outcome TEXT NOT NULL CHECK (
        outcome IN ('succeeded', 'failed', 'denied', 'requires_confirmation')
    ),
    error_code TEXT,
    retryable INTEGER CHECK (retryable IS NULL OR retryable IN (0, 1)),
    plan_revision INTEGER CHECK (plan_revision IS NULL OR plan_revision >= 1),
    plan_step_id TEXT,
    PRIMARY KEY (feedback_id, sequence),
    UNIQUE (feedback_id, call_id),
    CHECK ((plan_revision IS NULL) = (plan_step_id IS NULL)),
    FOREIGN KEY (feedback_id) REFERENCES execution_feedback(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_execution_feedback_actions_call
ON execution_feedback_actions(call_id);

CREATE TABLE IF NOT EXISTS execution_feedback_evidence (
    feedback_id TEXT NOT NULL,
    action_sequence INTEGER NOT NULL,
    source_evidence_index INTEGER NOT NULL CHECK (source_evidence_index >= 0),
    evidence_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    reference TEXT,
    source_call_id TEXT NOT NULL,
    PRIMARY KEY (feedback_id, action_sequence, source_evidence_index),
    FOREIGN KEY (feedback_id, action_sequence)
        REFERENCES execution_feedback_actions(feedback_id, sequence)
        ON DELETE CASCADE
);
"""

V6_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_feedback_plan_steps (
    feedback_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    step_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 1),
    objective TEXT NOT NULL,
    expected_outcome TEXT NOT NULL,
    original_status TEXT NOT NULL CHECK (
        original_status IN (
            'pending', 'running', 'completed', 'failed', 'stopped',
            'goal_not_achieved', 'superseded', 'cancelled'
        )
    ),
    outcome TEXT NOT NULL CHECK (
        outcome IN (
            'completed', 'failed', 'denied',
            'requires_confirmation', 'not_run'
        )
    ),
    stop_reason TEXT,
    error_code TEXT,
    safe_result_summary TEXT,
    evidence_refs_json TEXT NOT NULL,
    PRIMARY KEY (feedback_id, revision, step_id),
    UNIQUE (feedback_id, revision, position),
    FOREIGN KEY (feedback_id) REFERENCES execution_feedback(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO execution_feedback_plan_steps (
    feedback_id, revision, step_id, position, objective, expected_outcome,
    original_status, outcome, stop_reason, error_code, safe_result_summary,
    evidence_refs_json
)
SELECT
    feedback.id, step.revision, step.step_id, step.position,
    step.objective, step.expected_outcome, step.status,
    CASE
        WHEN step.status = 'completed' THEN 'completed'
        WHEN step.status = 'stopped' AND step.stop_reason = 'safety_denied'
            THEN 'denied'
        WHEN step.status = 'stopped' AND step.stop_reason = 'confirmation_required'
            THEN 'requires_confirmation'
        WHEN step.status IN ('pending', 'superseded', 'cancelled') THEN 'not_run'
        ELSE 'failed'
    END,
    step.stop_reason, step.error_code, step.safe_result_summary,
    step.evidence_refs_json
FROM execution_feedback AS feedback
JOIN plan_steps AS step
  ON step.plan_id = feedback.plan_id
 AND step.revision <= feedback.revision
WHERE feedback.path = 'planning';
"""

MIGRATIONS = (
    SchemaMigration(
        version=1,
        name="initial_canonical_schema",
        sql=V1_SCHEMA,
    ),
    SchemaMigration(
        version=2,
        name="plan_and_execute",
        sql=V2_SCHEMA,
    ),
    SchemaMigration(
        version=3,
        name="plan_confirmed_constraints",
        sql=V3_SCHEMA,
    ),
    SchemaMigration(
        version=4,
        name="memory_index",
        sql=V4_SCHEMA,
    ),
    SchemaMigration(
        version=5,
        name="execution_feedback",
        sql=V5_SCHEMA,
    ),
    SchemaMigration(
        version=6,
        name="execution_feedback_plan_step_snapshots",
        sql=V6_SCHEMA,
    ),
)

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version
