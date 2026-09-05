-- Deterministic Hydro logical keys; preflight duplicates before applying.
CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_leads_hydro_logical_key
  ON crm_leads (source_object_id)
  WHERE source_object_id LIKE 'hydro:%';
