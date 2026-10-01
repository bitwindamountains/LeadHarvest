-- v2: per-run options (e.g. {"js": true, "mx": true}) so `resume` keeps them.
ALTER TABLE runs ADD COLUMN options TEXT NOT NULL DEFAULT '{}';

-- MX results are cached so repeat runs don't repeat DNS lookups (TTL applied in code).
CREATE TABLE mx_cache (
    domain      TEXT PRIMARY KEY,
    has_mail    INTEGER NOT NULL,
    checked_at  TEXT NOT NULL
);
