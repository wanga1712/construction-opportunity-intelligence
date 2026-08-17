-- CRM-V3-LIVE-ANALYTICS-DASHBOARD-1 (addendum §50–80)
-- Controlled migration for persisted V3 analytics cache.
-- Apply ONLY to CRM DB (target owner: S13 CRM after cutover; never tender_monitor).
-- Do NOT run CREATE from analytics service at runtime (ANALYTICS_RUNTIME_DDL=NO).

CREATE TABLE IF NOT EXISTS crm_v3_analytics_generations (
    generation_id        BIGSERIAL PRIMARY KEY,
    status               TEXT NOT NULL
        CHECK (status IN ('BUILDING', 'COMPLETE', 'FAILED')),
    is_current           BOOLEAN NOT NULL DEFAULT FALSE,
    refresh_trigger      TEXT NOT NULL DEFAULT 'manual'
        CHECK (refresh_trigger IN ('manual', 'timer', 'test')),
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at          TIMESTAMPTZ,
    duration_ms          INTEGER,
    source_query_ms      INTEGER,
    crm_query_ms         INTEGER,
    cache_write_ms       INTEGER,
    error_summary        TEXT,
    routing_version      TEXT,
    registry_version     TEXT,
    registry_hash        TEXT,
    metrics_collected    INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_v3_analytics_one_current
    ON crm_v3_analytics_generations ((is_current))
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS idx_crm_v3_analytics_gen_status
    ON crm_v3_analytics_generations (status, finished_at DESC);

CREATE TABLE IF NOT EXISTS crm_v3_analytics_snapshots (
    id                   BIGSERIAL PRIMARY KEY,
    generation_id        BIGINT NOT NULL
        REFERENCES crm_v3_analytics_generations (generation_id) ON DELETE CASCADE,
    snapshot_key         TEXT NOT NULL,
    source_contour       TEXT,
    category_code        TEXT,
    opportunity_track    TEXT,
    medal_scope          TEXT,
    commercial_state     TEXT,
    metric_group         TEXT NOT NULL,
    metric_name          TEXT NOT NULL,
    metric_value         NUMERIC,
    payload_json         JSONB,
    data_as_of           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (generation_id, snapshot_key, metric_group, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_crm_v3_analytics_snap_gen
    ON crm_v3_analytics_snapshots (generation_id, metric_group);

CREATE INDEX IF NOT EXISTS idx_crm_v3_analytics_snap_dims
    ON crm_v3_analytics_snapshots (
        generation_id, source_contour, category_code, opportunity_track
    );

COMMENT ON TABLE crm_v3_analytics_generations IS
  'V3 analytics refresh generations. Only one COMPLETE is_current=true.';
COMMENT ON TABLE crm_v3_analytics_snapshots IS
  'Persisted aggregate metrics. No full procurement rows. Owner=S13_CRM_DB (target).';
