-- Migration to add version and registry hashes to autonomous analysis traces
ALTER TABLE crm_v3_autonomous_analysis_traces
ADD COLUMN IF NOT EXISTS registry_hash TEXT,
ADD COLUMN IF NOT EXISTS hunter_prompt_version TEXT,
ADD COLUMN IF NOT EXISTS auditor_prompt_version TEXT,
ADD COLUMN IF NOT EXISTS model_version TEXT,
ADD COLUMN IF NOT EXISTS attempt_count INT DEFAULT 1,
ADD COLUMN IF NOT EXISTS last_error TEXT;
