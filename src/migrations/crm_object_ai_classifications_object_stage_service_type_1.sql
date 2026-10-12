-- OBJECT-STAGE-SERVICE-TYPE-IMPLEMENTATION-V1
-- Additive migration only. Database: CRM DB.
--
-- Adds canonical storage for the two axes that were missing:
--   object_stage  -- lifecycle stage of the object
--                    (SURVEY / DESIGN / WORKING_DOCUMENTATION / EXPERTISE /
--                     CONSTRUCTION / OPERATION / UNKNOWN)
--   service_type  -- service subtype for SERVICES_OTHER procurements
--                    (CONSTRUCTION_CONTROL / AUTHOR_SUPERVISION /
--                     TECHNICAL_SURVEY / ENGINEERING_SURVEY / LAB_TESTING /
--                     MAINTENANCE_SERVICE / OTHER_SERVICE / NONE / UNKNOWN)
--
-- The existing column crm_object_ai_classifications.project_stage is a TENDER
-- stage with a different meaning. It is deliberately NOT renamed, NOT dropped
-- and NOT repurposed by this migration.

ALTER TABLE crm_object_ai_classifications
    ADD COLUMN IF NOT EXISTS object_stage TEXT,
    ADD COLUMN IF NOT EXISTS service_type TEXT;
