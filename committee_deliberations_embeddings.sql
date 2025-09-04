-- Global schema for embeddings, load manually (e.g., inside the db container):
-- psql -U postgres -d postgres -f /schema.sql

-- Vector extension for pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Committee deliberations embeddings table
-- NOTE: Ensure the dimension matches your embedding model.
-- For text-embedding-3-small use 1536; for 3-large use 3072.
CREATE TABLE IF NOT EXISTS committee_deliberations_embeddings (
    id            TEXT PRIMARY KEY,
    speech_id     TEXT UNIQUE NOT NULL,
    speaker       TEXT,
    speaker_role  TEXT,
    speaker_group TEXT,
    speech_text   TEXT NOT NULL,
    issue_id      TEXT,
    meeting_name  TEXT,
    date          TEXT,
    speech_url    TEXT,
    speech_order  INTEGER,
    embedding     VECTOR(1536),
    created_at    TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

