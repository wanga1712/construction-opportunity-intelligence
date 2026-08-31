-- Migration: Add temporal_class to crm_v3_learning_examples
-- Database: crm (CRM DB)

ALTER TABLE crm_v3_learning_examples
ADD COLUMN IF NOT EXISTS temporal_class VARCHAR(50) DEFAULT 'ONLINE_CLEAN';

ALTER TABLE crm_v3_learning_examples
DROP CONSTRAINT IF EXISTS crm_v3_learning_examples_temporal_class_check;

ALTER TABLE crm_v3_learning_examples
ADD CONSTRAINT crm_v3_learning_examples_temporal_class_check
CHECK (temporal_class IN ('ONLINE_CLEAN', 'BACKFILL_FACT_ONLY'));
