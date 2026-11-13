-- Allow planned UK activities to reference an existing Hydro object.
-- The activity remains in the canonical company_activities table.
ALTER TABLE company_activities
  ADD COLUMN IF NOT EXISTS object_id integer
    REFERENCES parking_prefunnel_objects (id) ON DELETE SET NULL;

ALTER TABLE company_activities
  ADD COLUMN IF NOT EXISTS contact_id integer
    REFERENCES company_contacts (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_activities_object
  ON company_activities (object_id);

CREATE INDEX IF NOT EXISTS idx_activities_contact
  ON company_activities (contact_id);
