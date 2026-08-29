-- Migration: Shadow Learning v2 Corrected Tables and Quarantining

ALTER TABLE crm_v3_pre_research_snapshots ADD COLUMN IF NOT EXISTS producer_version VARCHAR(64) DEFAULT 'v2_corrected';
ALTER TABLE crm_v3_shadow_predictions ADD COLUMN IF NOT EXISTS producer_version VARCHAR(64) DEFAULT 'v2_corrected';
ALTER TABLE crm_v3_exhaustive_truth ADD COLUMN IF NOT EXISTS producer_version VARCHAR(64) DEFAULT 'v2_corrected';
ALTER TABLE crm_v3_shadow_evaluations ADD COLUMN IF NOT EXISTS producer_version VARCHAR(64) DEFAULT 'v2_corrected';
ALTER TABLE crm_v3_learning_examples ADD COLUMN IF NOT EXISTS producer_version VARCHAR(64) DEFAULT 'v2_corrected';

-- Quarantine 7cdc invalid rows
UPDATE crm_v3_pre_research_snapshots SET producer_version = 'v1_invalid_7cdc' WHERE producer_version IS NULL OR producer_version = 'v1';
UPDATE crm_v3_shadow_predictions SET producer_version = 'v1_invalid_7cdc' WHERE producer_version IS NULL OR producer_version = 'v1';
UPDATE crm_v3_exhaustive_truth SET producer_version = 'v1_invalid_7cdc' WHERE producer_version IS NULL OR producer_version = 'v1';
UPDATE crm_v3_shadow_evaluations SET producer_version = 'v1_invalid_7cdc' WHERE producer_version IS NULL OR producer_version = 'v1';
UPDATE crm_v3_learning_examples SET producer_version = 'v1_invalid_7cdc' WHERE producer_version IS NULL OR producer_version = 'v1';
