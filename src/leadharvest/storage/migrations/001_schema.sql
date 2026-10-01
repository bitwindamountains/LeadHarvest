-- LeadHarvest schema v1 (blueprint section 9). Timestamps are ISO 8601 UTC text.

CREATE TABLE runs (
    id              TEXT PRIMARY KEY,
    category        TEXT NOT NULL,
    location        TEXT NOT NULL,
    area_id         INTEGER,
    area_kind       TEXT CHECK (area_kind IN ('area', 'bbox')),
    bbox            TEXT,
    area_name       TEXT,
    sources         TEXT NOT NULL,
    limit_n         INTEGER NOT NULL DEFAULT 200,
    export_targets  TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    current_step    TEXT NOT NULL
                    CHECK (current_step IN ('search', 'clean', 'enrich', 'score', 'export', 'done')),
    stats           TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE raw_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    UNIQUE (run_id, source, source_ref)
);
CREATE INDEX idx_raw_records_run ON raw_records(run_id);

CREATE TABLE leads (
    lead_id            TEXT PRIMARY KEY,
    business_name      TEXT NOT NULL,
    name_key           TEXT NOT NULL,
    categories         TEXT NOT NULL DEFAULT '[]',
    address            TEXT,
    city               TEXT,
    city_key           TEXT,
    city_source        TEXT,
    province           TEXT,
    street_key         TEXT,
    country            TEXT NOT NULL DEFAULT 'PH',
    lat                REAL,
    lon                REAL,
    phone              TEXT,
    phones_extra       TEXT NOT NULL DEFAULT '[]',
    email              TEXT,
    emails_extra       TEXT NOT NULL DEFAULT '[]',
    website            TEXT,
    final_url          TEXT,
    https_ok           INTEGER,
    domain             TEXT,
    facebook           TEXT,
    instagram          TEXT,
    linkedin           TEXT,
    tiktok             TEXT,
    opening_hours      TEXT,
    sources            TEXT NOT NULL DEFAULT '[]',
    enrich_status      TEXT NOT NULL DEFAULT 'pending'
                       CHECK (enrich_status IN ('pending', 'ok', 'no_website', 'robots_blocked',
                                                'timeout', 'http_error', 'failed')),
    enriched_at        TEXT,
    enrich_error       TEXT,
    score              INTEGER,
    flags              TEXT NOT NULL DEFAULT '[]',
    first_seen_run_id  TEXT NOT NULL,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX idx_leads_phone ON leads(phone);
CREATE INDEX idx_leads_domain_city ON leads(domain, city_key);
CREATE INDEX idx_leads_name_street_city ON leads(name_key, street_key, city_key);
CREATE INDEX idx_leads_last_seen ON leads(last_seen_at);

CREATE TABLE lead_sources (
    source      TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    lead_id     TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    PRIMARY KEY (source, source_ref)
);
CREATE INDEX idx_lead_sources_lead ON lead_sources(lead_id);

CREATE TABLE run_leads (
    run_id    TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    lead_id   TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    category  TEXT NOT NULL,
    position  INTEGER NOT NULL,
    PRIMARY KEY (run_id, lead_id)
);
CREATE INDEX idx_run_leads_lead ON run_leads(lead_id);

CREATE TABLE suppressions (
    kind        TEXT NOT NULL CHECK (kind IN ('domain', 'phone', 'email')),
    value       TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (kind, value)
);

CREATE TABLE geo_cache (
    query_key  TEXT PRIMARY KEY,
    result     TEXT NOT NULL,
    cached_at  TEXT NOT NULL
);

CREATE TABLE robots_cache (
    origin      TEXT PRIMARY KEY,
    robots_txt  TEXT,
    status      INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL
);
