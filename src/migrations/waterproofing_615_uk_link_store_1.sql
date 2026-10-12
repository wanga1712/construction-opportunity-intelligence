-- WATERPROOFING-615-UK-LINK-STORE-1
-- CRM-owned derived store for the waterproofing УК board (615-ПП linkage).
-- Apply ONLY to the canonical CRM DB (S13) as the runtime role `crm_app`.
-- NEVER apply to tender_monitor / S7: source tables stay read-only for CRM.
-- Runtime code performs no DDL; it only reads/refreshes these tables.
--
-- Truth model:
--   crm_waterproofing_615_program_year   — объём всей программы 615-ПП по годам
--   crm_waterproofing_615_uk_address     — все проверенные дома портфеля УК
--   crm_waterproofing_615_uk_link        — найденные контракты на домах УК
--   crm_waterproofing_615_sync_state     — свежесть и результат обновления

CREATE TABLE IF NOT EXISTS crm_waterproofing_615_program_year (
    year                  INTEGER PRIMARY KEY,
    tenders               INTEGER NOT NULL DEFAULT 0,
    amount                NUMERIC(20, 2) NOT NULL DEFAULT 0,
    waterproofing_tenders INTEGER NOT NULL DEFAULT 0,
    waterproofing_amount  NUMERIC(20, 2) NOT NULL DEFAULT 0,
    refreshed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE crm_waterproofing_615_program_year IS
  '615-ПП: объём всей программы капремонта по годам (все адреса, не только дома УК).';

CREATE TABLE IF NOT EXISTS crm_waterproofing_615_uk_address (
    id              BIGSERIAL PRIMARY KEY,
    uk_key          TEXT NOT NULL,
    address_key     TEXT NOT NULL,
    address_text    TEXT,
    match_method    TEXT NOT NULL DEFAULT 'none',
    match_score     REAL NOT NULL DEFAULT 0,
    contracts_count INTEGER NOT NULL DEFAULT 0,
    matched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (uk_key, address_key)
);

CREATE INDEX IF NOT EXISTS idx_wp615_uk_address_uk
    ON crm_waterproofing_615_uk_address (uk_key);

COMMENT ON TABLE crm_waterproofing_615_uk_address IS
  '615-ПП: каждый дом портфеля УК и результат сопоставления с торгами капремонта.';

CREATE TABLE IF NOT EXISTS crm_waterproofing_615_uk_link (
    id               BIGSERIAL PRIMARY KEY,
    uk_key           TEXT NOT NULL,
    address_key      TEXT NOT NULL,
    address_text     TEXT,
    contract_id      TEXT NOT NULL,
    contract_number  TEXT,
    contract_date    DATE,
    contract_year    INTEGER,
    amount           NUMERIC(20, 2) NOT NULL DEFAULT 0,
    is_waterproofing BOOLEAN NOT NULL DEFAULT FALSE,
    match_method     TEXT NOT NULL DEFAULT 'exact',
    match_score      REAL NOT NULL DEFAULT 0,
    matched_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (uk_key, address_key, contract_id)
);

CREATE INDEX IF NOT EXISTS idx_wp615_uk_link_uk
    ON crm_waterproofing_615_uk_link (uk_key);
CREATE INDEX IF NOT EXISTS idx_wp615_uk_link_year
    ON crm_waterproofing_615_uk_link (contract_year);

COMMENT ON TABLE crm_waterproofing_615_uk_link IS
  '615-ПП: контракты капремонта, найденные на домах УК (заказчик ФКР, связка по адресу).';

CREATE TABLE IF NOT EXISTS crm_waterproofing_615_sync_state (
    source              TEXT PRIMARY KEY,
    status              TEXT NOT NULL,
    last_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_success_at     TIMESTAMPTZ,
    duration_ms         INTEGER,
    source_contracts    INTEGER NOT NULL DEFAULT 0,
    history_from_year   INTEGER,
    checked_addresses   INTEGER NOT NULL DEFAULT 0,
    link_rows           INTEGER NOT NULL DEFAULT 0,
    uk_with_tenders     INTEGER NOT NULL DEFAULT 0,
    safe_error_class    TEXT,
    safe_error_message  TEXT
);

COMMENT ON TABLE crm_waterproofing_615_sync_state IS
  '615-ПП: свежесть и результат последнего обновления связки (источник -> CRM).';

INSERT INTO crm_waterproofing_615_sync_state (source, status)
VALUES ('TENDER_MONITOR_615', 'NEVER_RUN')
ON CONFLICT (source) DO NOTHING;