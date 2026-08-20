-- CRM-V3-MODEL-AUTHORITY-RESTORATION-1 / Phase 6B
-- Additive business-rule result + field provenance on assessments.
-- Apply ONLY via the canonical S13 DDL admin route:
--   approved SSH host alias from PROJECT_OPERATING_RULES.md, then:
--   sudo -n -u postgres psql -d crm -f <this file>
-- Do NOT apply from Streamlit/runtime.
-- Do NOT change table ownership.
-- Do NOT synthesize historical inference runs.

ALTER TABLE procurement_ai_assessments
    ADD COLUMN IF NOT EXISTS business_rule_result JSONB;

ALTER TABLE procurement_ai_assessments
    ADD COLUMN IF NOT EXISTS field_provenance JSONB;

COMMENT ON COLUMN procurement_ai_assessments.business_rule_result IS
    'Phase 6B BUSINESS namespace: route/scope/priors/score/medal/timing. NOT model authority.';

COMMENT ON COLUMN procurement_ai_assessments.field_provenance IS
    'Phase 6B per-field provenance map (MODEL_VALIDATED|MODEL_DERIVED|BUSINESS_RULE|...).';

COMMENT ON COLUMN procurement_ai_assessments.normalized_result IS
    'COMPATIBILITY / BUSINESS-ENRICHED result. NOT model authority. Model authority is crm_v3_model_inference_runs.validated_model_result via inference_run_id.';
