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
)

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version
