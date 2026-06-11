-- supabase/migrations/001_initial.sql
-- Run this first. Creates the base incident memory table used by memory_agent.py.

-- Enable pgvector for future similarity search (002 uses it)
create extension if not exists vector;

-- ── incident_memory ──────────────────────────────────────────────────────────
-- Raw episode storage. One row per resolved incident.
-- Matches the record structure in agents/memory_agent.py :: store()

create table if not exists incident_memory (
    id               text primary key,
    created_at       timestamptz default now(),
    incident_id      text not null,
    incident_prompt  text not null,
    root_cause       text,
    confidence_score float default 0.0,
    fix_applied      boolean default false,
    fix_blocked      boolean default false,
    notion_url       text,
    scripts_count    int default 0,
    scripts_json     text          -- JSON string, capped at 5000 chars in memory_agent.py
);

-- Fast lookups by recency (current memory_agent.py uses order by created_at desc)
create index if not exists idx_incident_memory_created_at
    on incident_memory (created_at desc);

-- Fast lookups by incident_id (for deduplication checks)
create index if not exists idx_incident_memory_incident_id
    on incident_memory (incident_id);
