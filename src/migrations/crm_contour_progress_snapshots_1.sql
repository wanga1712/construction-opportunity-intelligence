-- PHYSICAL S13 PROGRESS SNAPSHOTS + 24H DELTA
-- Persistent snapshots so the physical monitor never runs heavy COUNTs itself.
-- Additive and idempotent. No DELETE/rename. Apply as owner role crm_app.

BEGIN;

SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS crm_contour_progress_snapshots (
    id                       BIGSERIAL PRIMARY KEY,
    captured_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    eligible_total           INTEGER,
    processed_total          INTEGER,
    remaining_total          INTEGER,
    in_progress              INTEGER,

    deterministic_accept     INTEGER,
    no_commercial_entry      INTEGER,
    qwen_processed           INTEGER,
    classified_total         INTEGER,

    backlog_drain_remaining  INTEGER,

    gold                     INTEGER,
    silver                   INTEGER,
    bronze                   INTEGER,
    wood                     INTEGER,

    failed                   INTEGER,
    blocked                  INTEGER,

    document_pending         INTEGER,
    document_processing      INTEGER,
    document_completed_total INTEGER,
    document_no_links        INTEGER,
    document_failed          INTEGER,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS crm_contour_progress_snapshots_captured_idx
    ON crm_contour_progress_snapshots (captured_at DESC);

CREATE TABLE IF NOT EXISTS crm_contour_category_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category_code TEXT NOT NULL,
    total         INTEGER,
    classified    INTEGER,
    unclassified  INTEGER,
    coverage_pct  NUMERIC(6,2),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS crm_contour_category_snapshots_lookup_idx
    ON crm_contour_category_snapshots (captured_at DESC, category_code);

COMMIT;
