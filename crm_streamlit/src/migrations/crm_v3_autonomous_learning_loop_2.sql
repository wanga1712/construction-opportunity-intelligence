-- Migration to add category validation and completeness columns
ALTER TABLE crm_v3_product_findings
ADD COLUMN IF NOT EXISTS raw_model_category_code TEXT,
ADD COLUMN IF NOT EXISTS category_validation_status TEXT;

ALTER TABLE crm_v3_autonomous_analysis_traces
ADD COLUMN IF NOT EXISTS research_completeness TEXT;
