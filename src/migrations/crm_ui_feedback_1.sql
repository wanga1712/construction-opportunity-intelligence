-- Additive: UI labelling + category stop-phrases + priority research requests.
-- No deletes, no renames; safe to run repeatedly.

CREATE TABLE IF NOT EXISTS crm_ui_feedback (
    id            BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    category_code TEXT,
    polarity      TEXT NOT NULL CHECK (polarity IN ('POSITIVE', 'NEGATIVE')),
    label_source  TEXT NOT NULL DEFAULT 'UI_LABEL',
    comment       TEXT,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_crm_ui_feedback_proc ON crm_ui_feedback (procurement_id);
CREATE INDEX IF NOT EXISTS idx_crm_ui_feedback_cat ON crm_ui_feedback (category_code, polarity);

CREATE TABLE IF NOT EXISTS crm_category_stop_phrases (
    id            BIGSERIAL PRIMARY KEY,
    category_code TEXT NOT NULL,
    phrase        TEXT NOT NULL,
    okpd          TEXT,
    polarity      TEXT NOT NULL DEFAULT 'NEGATIVE' CHECK (polarity IN ('NEGATIVE', 'POSITIVE')),
    source        TEXT NOT NULL DEFAULT 'UI_LABEL',
    hits          INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category_code, phrase, polarity)
);
CREATE INDEX IF NOT EXISTS idx_crm_cat_stop_active ON crm_category_stop_phrases (category_code, is_active);

CREATE TABLE IF NOT EXISTS crm_research_requests (
    id             BIGSERIAL PRIMARY KEY,
    procurement_id BIGINT NOT NULL,
    target_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
    priority       INTEGER NOT NULL DEFAULT 100,
    status         TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'QUEUED', 'RUNNING', 'DONE', 'CANCELLED')),
    requested_by   TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (procurement_id)
);
CREATE INDEX IF NOT EXISTS idx_crm_research_req_priority ON crm_research_requests (status, priority DESC);
