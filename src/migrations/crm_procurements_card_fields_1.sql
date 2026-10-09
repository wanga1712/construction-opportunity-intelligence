-- Additive card-enrichment fields for «Карточка закупки» (source: S7 tender_monitor).
-- Idempotent, no data change here (backfill is a separate step). Owner: postgres.
SET LOCAL lock_timeout = '10s';

ALTER TABLE crm_procurements
    ADD COLUMN IF NOT EXISTS trading_platform text,      -- ЭТП (источник: trading_platform)
    ADD COLUMN IF NOT EXISTS source_status text,         -- статус источника (tender_statuses)
    ADD COLUMN IF NOT EXISTS delivery_address text,      -- адрес поставки (delivery_address)
    ADD COLUMN IF NOT EXISTS guarantee_amount numeric,   -- обеспечение (guarantee_amount)
    ADD COLUMN IF NOT EXISTS warranty_size text;         -- гарантия (warranty_size)
