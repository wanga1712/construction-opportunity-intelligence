-- CRM-V3-ROUTING-CONTRACT-PRE-GOLDEN-BLOCKER-FIX-1
-- Controlled migration only. NO runtime auto-DDL.

ALTER TABLE crm_procurements
  ADD COLUMN IF NOT EXISTS ai_routing_attempt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE crm_procurements
  ADD COLUMN IF NOT EXISTS ai_routing_error_class VARCHAR(64);
