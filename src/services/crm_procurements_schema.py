"""DDL и bootstrap для таблиц закупок CRM."""
from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS crm_procurements (
    id                      SERIAL PRIMARY KEY,
    source_table            TEXT NOT NULL,
    source_id               INTEGER NOT NULL,
    contract_number         TEXT NOT NULL,
    auction_name            TEXT NOT NULL,
    initial_price           NUMERIC,
    final_price             NUMERIC,
    customer                TEXT,
    delivery_region         TEXT,
    region_id               INTEGER,
    okpd_code               TEXT,
    okpd_name               TEXT,
    contractor_name         TEXT,
    contractor_inn          TEXT,
    start_date              DATE,
    end_date                DATE,
    delivery_start_date     DATE,
    delivery_end_date       DATE,
    tender_link             TEXT,

    -- CRM-стадия
    crm_stage               TEXT NOT NULL DEFAULT 'torgi',
    award_status            TEXT NOT NULL DEFAULT 'submission_open',

    -- Ожидание результата после окончания подачи
    post_submission_grace_days SMALLINT NOT NULL DEFAULT 14
        CHECK (post_submission_grace_days BETWEEN 1 AND 30),
    last_award_check_at     TIMESTAMPTZ,
    next_award_check_at     TIMESTAMPTZ,

    -- Поля из awarded-реестра (заполняются после розыгрыша)
    award_date              DATE,
    winner_name             TEXT,
    winner_inn              TEXT,
    final_contract_price    NUMERIC,
    contract_signed_at      DATE,
    execution_start_at      DATE,
    execution_end_at        DATE,
    source_awarded_table    TEXT,
    source_awarded_id       INTEGER,
    awarded_match_type      TEXT,
    awarded_match_confidence NUMERIC,
    commercial_window_state TEXT,
    deadline_trust          TEXT CHECK (deadline_trust IN ('TRUSTED', 'RECOVERED', 'UNRECOVERABLE_LEGACY')),

    -- Метаданные
    crm_created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    crm_updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_updated_at       TIMESTAMPTZ,

    UNIQUE (source_table, source_id)
);

CREATE INDEX IF NOT EXISTS idx_crm_procurements_stage
    ON crm_procurements (crm_stage, award_status);
CREATE INDEX IF NOT EXISTS idx_crm_procurements_end_date
    ON crm_procurements (end_date DESC);
CREATE INDEX IF NOT EXISTS idx_crm_procurements_okpd
    ON crm_procurements (okpd_code);
CREATE INDEX IF NOT EXISTS idx_crm_procurements_region
    ON crm_procurements (region_id);

-- Задания синхронизации
CREATE TABLE IF NOT EXISTS crm_sync_jobs (
    id              SERIAL PRIMARY KEY,
    job_type        TEXT NOT NULL DEFAULT 'active_to_awarded',
    trigger_type    TEXT NOT NULL DEFAULT 'scheduled',
    requested_by    TEXT,
    status          TEXT NOT NULL DEFAULT 'queued',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    processed_count INTEGER NOT NULL DEFAULT 0,
    updated_count   INTEGER NOT NULL DEFAULT 0,
    awarded_count   INTEGER NOT NULL DEFAULT 0,
    not_found_count INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Журнал переходов
CREATE TABLE IF NOT EXISTS crm_sync_events (
    id                   SERIAL PRIMARY KEY,
    sync_job_id          INTEGER REFERENCES crm_sync_jobs(id),
    procurement_id       INTEGER REFERENCES crm_procurements(id),
    old_stage            TEXT,
    new_stage            TEXT,
    old_status           TEXT,
    new_status           TEXT,
    source_table         TEXT,
    source_external_id   TEXT,
    match_type           TEXT,
    match_confidence     NUMERIC,
    result_code          TEXT,
    details_json         JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Настройки CRM
CREATE TABLE IF NOT EXISTS crm_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO crm_settings (key, value) VALUES
    ('post_submission_grace_days', '14'),
    ('sync_schedule_cron', '0 11 * * *'),
    ('sync_last_run_at', ''),
    ('sync_next_run_at', '')
ON CONFLICT (key) DO NOTHING;
"""


def ensure_schema(crm_db) -> bool:
    """Fail-closed presence check. DDL is not executed at runtime.

    Canonical DDL text remains in this module for documentation / migration
    extraction; apply via controlled migration scripts only.
    """
    from src.services.schema_guard import require_relations

    ok, missing = require_relations(
        crm_db,
        ["crm_procurements", "crm_sync_jobs", "crm_sync_events", "crm_settings"],
    )
    if not ok:
        import logging

        logging.getLogger(__name__).error(
            "crm_procurements_schema NOT_READY missing=%s (no runtime DDL)", missing
        )
    return ok
