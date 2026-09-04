-- Phase 1 Hydro canonical data. Apply to CRM DB only after operator approval.
-- This file is intentionally NOT applied by this WIP.

ALTER TABLE parking_prefunnel_objects
  ADD COLUMN IF NOT EXISTS source_system varchar(40),
  ADD COLUMN IF NOT EXISTS source_object_id varchar(120),
  ADD COLUMN IF NOT EXISTS source_external_object_id varchar(120),
  ADD COLUMN IF NOT EXISTS purpose text,
  ADD COLUMN IF NOT EXISTS object_type varchar(160),
  ADD COLUMN IF NOT EXISTS lat double precision,
  ADD COLUMN IF NOT EXISTS lon double precision,
  ADD COLUMN IF NOT EXISTS floors_total integer,
  ADD COLUMN IF NOT EXISTS construction_finish_year integer,
  ADD COLUMN IF NOT EXISTS commissioning_year integer,
  ADD COLUMN IF NOT EXISTS area_total double precision,
  ADD COLUMN IF NOT EXISTS wall_material varchar(160),
  ADD COLUMN IF NOT EXISTS parking_type varchar(40),
  ADD COLUMN IF NOT EXISTS parking_confidence double precision,
  ADD COLUMN IF NOT EXISTS parking_candidate_reason text,
  ADD COLUMN IF NOT EXISTS management_status varchar(40),
  ADD COLUMN IF NOT EXISTS management_type varchar(120),
  ADD COLUMN IF NOT EXISTS source_updated_at timestamptz,
  ADD COLUMN IF NOT EXISTS first_seen_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_seen_at timestamptz,
  ADD COLUMN IF NOT EXISTS synced_at timestamptz,
  ADD COLUMN IF NOT EXISTS source_payload jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ppf_objects_source_identity
  ON parking_prefunnel_objects (source_system, source_object_id)
  WHERE source_system IS NOT NULL AND source_object_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS crm_hydro_source_health (
  source varchar(40) PRIMARY KEY,
  last_attempt_at timestamptz,
  last_success_at timestamptz,
  status varchar(20) NOT NULL CHECK (status IN ('SUCCESS','FAILED','PARTIAL','NEVER_SYNCED')),
  rows_seen integer NOT NULL DEFAULT 0,
  rows_inserted integer NOT NULL DEFAULT 0,
  rows_updated integer NOT NULL DEFAULT 0,
  rows_unchanged integer NOT NULL DEFAULT 0,
  rows_invalid integer NOT NULL DEFAULT 0,
  safe_error_class varchar(120), safe_error_message text
);

CREATE TABLE IF NOT EXISTS crm_hydro_lead_extensions (
  lead_id integer PRIMARY KEY REFERENCES crm_leads(id) ON DELETE CASCADE,
  lead_kind varchar(30) NOT NULL CHECK (lead_kind IN ('COMPANY_CONTOUR','STANDALONE_OBJECT')),
  hydro_state varchar(30) NOT NULL DEFAULT 'NEW',
  management_company_id integer REFERENCES management_companies(id) ON DELETE SET NULL,
  merged_into_lead_id integer REFERENCES crm_leads(id) ON DELETE SET NULL,
  object_potential jsonb, lead_readiness jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crm_hydro_lead_objects (
  lead_id integer NOT NULL REFERENCES crm_leads(id) ON DELETE CASCADE,
  parking_object_id integer NOT NULL REFERENCES parking_prefunnel_objects(id) ON DELETE CASCADE,
  relation_method varchar(30) NOT NULL CHECK (relation_method IN ('SOURCE_ID','CADASTRAL_NUMBER','HEURISTIC_REVIEW')),
  relation_confidence numeric CHECK (relation_confidence IS NULL OR relation_confidence BETWEEN 0 AND 1),
  is_primary boolean NOT NULL DEFAULT false,
  selected_for_survey boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (lead_id, parking_object_id),
  UNIQUE (parking_object_id)
);

CREATE INDEX IF NOT EXISTS idx_crm_hydro_lead_objects_lead ON crm_hydro_lead_objects (lead_id);
CREATE INDEX IF NOT EXISTS idx_crm_hydro_ext_state ON crm_hydro_lead_extensions (hydro_state);
