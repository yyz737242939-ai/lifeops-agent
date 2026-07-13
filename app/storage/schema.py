"""SQLite schema definitions."""

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

V1_INITIAL_STORAGE_SCHEMA = """
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
"""

V2_RESEARCH_SOURCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_sources (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_sources_source_key
ON research_sources(source_key);
"""

V3_TRAVEL_ITINERARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS travel_itineraries (
    id TEXT PRIMARY KEY,
    destination TEXT NOT NULL,
    transport TEXT NOT NULL,
    lodging TEXT NOT NULL,
    summary TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_travel_itineraries_destination
ON travel_itineraries(destination);
"""

V4_RESEARCH_KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_topics (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

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
    position INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (brief_id, source_id),
    UNIQUE (brief_id, position),
    FOREIGN KEY (brief_id) REFERENCES research_briefs(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES research_sources(id) ON DELETE RESTRICT
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

CREATE TABLE IF NOT EXISTS research_revisions (
    id TEXT PRIMARY KEY,
    item_kind TEXT NOT NULL CHECK (item_kind IN ('topic', 'source', 'note', 'brief')),
    item_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (item_kind, item_id, version)
);

CREATE INDEX IF NOT EXISTS idx_research_links_from_item
ON research_links(from_kind, from_id);

CREATE INDEX IF NOT EXISTS idx_research_links_to_item
ON research_links(to_kind, to_id);

CREATE INDEX IF NOT EXISTS idx_research_revisions_item
ON research_revisions(item_kind, item_id, version);
"""

V5_RESEARCH_SOURCE_SNAPSHOT_SCHEMA = """
ALTER TABLE research_sources RENAME TO research_sources_legacy;
ALTER TABLE research_brief_sources RENAME TO research_brief_sources_legacy;

CREATE TABLE research_sources (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE research_source_snapshots (
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

INSERT INTO research_sources (id, source_key, url, title, source_type, created_at)
SELECT id, source_key, url, title, 'web_page', created_at
FROM research_sources_legacy;

INSERT INTO research_source_snapshots (
    id, source_id, summary, content_hash, fetched_at,
    published_at, provenance, created_at
)
SELECT 'snapshot-migrated-' || id, id, summary, content_hash, fetched_at,
       NULL, provenance, created_at
FROM research_sources_legacy;

CREATE TABLE research_brief_sources (
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

INSERT INTO research_brief_sources (brief_id, source_id, snapshot_id, position)
SELECT brief_id, source_id, 'snapshot-migrated-' || source_id, position
FROM research_brief_sources_legacy;

DROP TABLE research_brief_sources_legacy;
DROP TABLE research_sources_legacy;

CREATE INDEX idx_research_sources_source_key
ON research_sources(source_key);

CREATE INDEX idx_research_source_snapshots_source_id
ON research_source_snapshots(source_id, fetched_at DESC);
"""

V6_TRAVEL_DOMAIN_SCHEMA = """
CREATE TABLE trips (
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

CREATE TABLE travel_constraints (
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

ALTER TABLE travel_itineraries ADD COLUMN trip_id TEXT REFERENCES trips(id) ON DELETE RESTRICT;
ALTER TABLE travel_itineraries ADD COLUMN draft_id TEXT;
ALTER TABLE travel_itineraries ADD COLUMN idempotency_key TEXT;
ALTER TABLE travel_itineraries ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);

CREATE UNIQUE INDEX idx_travel_itineraries_idempotency_key
ON travel_itineraries(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE TABLE travel_itinerary_items (
    id TEXT PRIMARY KEY,
    itinerary_id TEXT NOT NULL,
    day_number INTEGER NOT NULL CHECK (day_number >= 1),
    title TEXT NOT NULL,
    item_type TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    source_candidate_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (itinerary_id) REFERENCES travel_itineraries(id) ON DELETE CASCADE
);

CREATE TABLE travel_decisions (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('calendar', 'destination', 'itinerary', 'lodging', 'place', 'transport')
    ),
    selected_candidate_ids_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
);

CREATE TABLE travel_knowledge_refs (
    trip_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (trip_id, domain, item_kind, item_id),
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
);

CREATE INDEX idx_travel_constraints_trip
ON travel_constraints(trip_id, kind, created_at, id);

CREATE INDEX idx_travel_itineraries_trip
ON travel_itineraries(trip_id, created_at, id);

CREATE INDEX idx_travel_itinerary_items_itinerary
ON travel_itinerary_items(itinerary_id, day_number, starts_at, id);

CREATE INDEX idx_travel_decisions_trip
ON travel_decisions(trip_id, decided_at, id);
"""

V7_TRAVEL_ITINERARY_DETAIL_SCHEMA = """
ALTER TABLE travel_itinerary_items RENAME TO travel_itinerary_items_v6;
ALTER TABLE travel_decisions RENAME TO travel_decisions_v6;

CREATE TABLE travel_itinerary_items (
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

CREATE TABLE travel_decisions (
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

INSERT INTO travel_itinerary_items (
    id, itinerary_id, day_number, title, item_type,
    starts_at, ends_at, source_candidate_id, notes, created_at
)
SELECT id, itinerary_id, day_number, title, item_type,
       starts_at, ends_at, source_candidate_id, notes, created_at
FROM travel_itinerary_items_v6;

INSERT INTO travel_decisions (
    id, trip_id, itinerary_id, kind,
    selected_candidate_ids_json, rationale, decided_at
)
SELECT id, trip_id, NULL, kind,
       selected_candidate_ids_json, rationale, decided_at
FROM travel_decisions_v6;

DROP TABLE travel_itinerary_items_v6;
DROP TABLE travel_decisions_v6;

CREATE INDEX idx_travel_itinerary_items_itinerary
ON travel_itinerary_items(itinerary_id, day_number, starts_at, id);

CREATE INDEX idx_travel_decisions_trip
ON travel_decisions(trip_id, decided_at, id);
"""

V8_TRAVEL_KNOWLEDGE_REFERENCE_SCHEMA = """
ALTER TABLE travel_knowledge_refs RENAME TO travel_knowledge_refs_v7;

CREATE TABLE travel_knowledge_refs (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (trip_id, domain, item_kind, item_id),
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
);

INSERT INTO travel_knowledge_refs (
    id, trip_id, domain, item_kind, item_id, created_at
)
SELECT 'knowledge-ref-migrated-' || rowid,
       trip_id, domain, item_kind, item_id, created_at
FROM travel_knowledge_refs_v7;

DROP TABLE travel_knowledge_refs_v7;

CREATE INDEX idx_travel_knowledge_refs_trip
ON travel_knowledge_refs(trip_id, created_at, id);
"""

MIGRATIONS = (
    SchemaMigration(
        version=1,
        name="initial_storage_schema",
        sql=V1_INITIAL_STORAGE_SCHEMA,
    ),
    SchemaMigration(
        version=2,
        name="research_source_schema",
        sql=V2_RESEARCH_SOURCE_SCHEMA,
    ),
    SchemaMigration(
        version=3,
        name="travel_itinerary_schema",
        sql=V3_TRAVEL_ITINERARY_SCHEMA,
    ),
    SchemaMigration(
        version=4,
        name="research_knowledge_schema",
        sql=V4_RESEARCH_KNOWLEDGE_SCHEMA,
    ),
    SchemaMigration(
        version=5,
        name="research_source_snapshot_schema",
        sql=V5_RESEARCH_SOURCE_SNAPSHOT_SCHEMA,
    ),
    SchemaMigration(
        version=6,
        name="travel_domain_schema",
        sql=V6_TRAVEL_DOMAIN_SCHEMA,
    ),
    SchemaMigration(
        version=7,
        name="travel_itinerary_detail_schema",
        sql=V7_TRAVEL_ITINERARY_DETAIL_SCHEMA,
    ),
    SchemaMigration(
        version=8,
        name="travel_knowledge_reference_schema",
        sql=V8_TRAVEL_KNOWLEDGE_REFERENCE_SCHEMA,
    ),
)

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version
