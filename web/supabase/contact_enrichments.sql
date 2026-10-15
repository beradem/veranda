-- Contact enrichment cache (Minerva).
--
-- Run once in the Supabase SQL editor.
--
-- Why a separate table instead of columns on `leads`: the quarterly sync
-- (scripts/sync_leads.py) deletes and re-inserts every lead. Paid contact
-- lookups live here so they survive re-syncs and we never pay twice.

CREATE TABLE IF NOT EXISTS contact_enrichments (
    name_key     TEXT        NOT NULL,
    zip_code     TEXT        NOT NULL DEFAULT '',
    provider     TEXT        NOT NULL DEFAULT 'minerva',
    is_match     BOOLEAN     NOT NULL,
    minerva_pid  TEXT,
    contact      JSONB,               -- phones, emails, LinkedIn — see web/lib/minerva.ts
    enriched_by  UUID,                -- auth.users.id of whoever opened the lead
    enriched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (name_key, zip_code)
);

CREATE INDEX IF NOT EXISTS idx_contact_enrichments_user_time
    ON contact_enrichments (enriched_by, enriched_at);

-- Personal contact data: lock the table to the server's service key only.
-- With RLS on and no policies, the public anon key (shipped to browsers)
-- cannot read or write it.
ALTER TABLE contact_enrichments ENABLE ROW LEVEL SECURITY;
