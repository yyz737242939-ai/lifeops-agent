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
)

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version
