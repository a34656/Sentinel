-- supabase/migrations/002_memory_layers.sql
-- Run after 001_initial.sql.
-- Adds Layer 2 (episodic with decay + vector search) and
-- Layer 3 (semantic rules extracted by consolidation job).

-- ── LAYER 2: episodic_memory ──────────────────────────────────────────────────
-- Replaces the flat incident_memory for new incidents going forward.
-- Adds: decay_score, reinforcement_count, embedding for similarity search,
-- and a TTL-style archive flag.

create table if not exists episodic_memory (
    id                  uuid primary key default gen_random_uuid(),
    created_at          timestamptz default now(),
    last_reinforced_at  timestamptz default now(),

    -- Incident data
    incident_id         text not null,
    incident_prompt     text not null,
    root_cause          text,
    resolution          text,
    confidence_score    float default 0.0,
    fix_applied         boolean default false,
    tags                text[] default '{}',

    -- Memory health
    decay_score         float default 1.0,   -- 1.0 = fresh, decays toward 0
    reinforcement_count int default 0,        -- how many times this memory was confirmed correct
    is_archived         boolean default false, -- moved to cold storage after decay

    -- Vector embedding for similarity search (1536-dim for text-embedding-3-small)
    -- Use 8-dim for the lightweight embedding in memory_layers.py
    embedding           vector(8)
);

create index if not exists idx_episodic_memory_created_at
    on episodic_memory (created_at desc);

create index if not exists idx_episodic_memory_active
    on episodic_memory (is_archived, decay_score desc)
    where is_archived = false;

create index if not exists idx_episodic_memory_tags
    on episodic_memory using gin (tags);

create index if not exists idx_episodic_memory_embedding
    on episodic_memory using ivfflat (embedding vector_cosine_ops)
    with (lists = 10);

-- ── LAYER 3: semantic_rules ───────────────────────────────────────────────────
-- Human-readable, AI-readable generalised rules.
-- Written by consolidation.py nightly from Layer 2 episodes.
-- Humans can edit these directly in Supabase dashboard or Obsidian.
-- These are injected first into every new investigation (~500 tokens).

create table if not exists semantic_rules (
    id              uuid primary key default gen_random_uuid(),
    created_at      timestamptz default now(),
    updated_at      timestamptz default now(),
    source          text default 'consolidation',  -- 'consolidation' | 'human' | 'obsidian'

    -- The rule itself
    rule_text       text not null,   -- e.g. "CPU spikes Mon 9-11am are normal batch job"
    applies_to      text[] default '{}',  -- tags: ['aws', 'ec2', 'billing']
    confidence      float default 0.8,    -- how strongly this rule holds

    -- Lifecycle
    times_applied   int default 0,        -- how many investigations used this rule
    times_confirmed int default 0,        -- how many times it proved correct
    times_wrong     int default 0,        -- how many times it was wrong (triggers review)
    is_active       boolean default true,

    -- Human override
    human_reviewed  boolean default false,
    human_note      text
);

create index if not exists idx_semantic_rules_active
    on semantic_rules (is_active, confidence desc)
    where is_active = true;

create index if not exists idx_semantic_rules_tags
    on semantic_rules using gin (applies_to);

-- ── obsidian_sync ─────────────────────────────────────────────────────────────
-- Tracks which Obsidian vault notes have been synced and when.
-- Written by tools/obsidian_sync.py.

create table if not exists obsidian_sync (
    id              uuid primary key default gen_random_uuid(),
    synced_at       timestamptz default now(),
    file_path       text not null unique,  -- relative path in vault
    file_hash       text not null,         -- SHA256 of content for change detection
    note_type       text default 'general', -- 'runbook' | 'postmortem' | 'architecture' | 'general'
    tags            text[] default '{}',
    content_preview text                   -- first 500 chars for search
);

-- ── RPC: match_episodic_memories ─────────────────────────────────────────────
-- Used by core/memory_layers.py :: query_layer2()
-- Returns top-K similar episodes by vector cosine similarity.

create or replace function match_episodic_memories(
    query_embedding  vector(8),
    match_threshold  float default 0.6,
    match_count      int default 3
)
returns table (
    id               uuid,
    incident_id      text,
    incident_prompt  text,
    root_cause       text,
    resolution       text,
    confidence_score float,
    decay_score      float,
    similarity       float
)
language sql stable
as $$
    select
        id,
        incident_id,
        incident_prompt,
        root_cause,
        resolution,
        confidence_score,
        decay_score,
        1 - (embedding <=> query_embedding) as similarity
    from episodic_memory
    where
        is_archived = false
        and 1 - (embedding <=> query_embedding) > match_threshold
    order by
        -- Blend similarity with decay_score so fresh memories rank higher
        (1 - (embedding <=> query_embedding)) * decay_score desc
    limit match_count;
$$;

-- ── Trigger: update semantic_rules.updated_at on edit ────────────────────────

create or replace function _set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger semantic_rules_updated_at
    before update on semantic_rules
    for each row execute function _set_updated_at();
