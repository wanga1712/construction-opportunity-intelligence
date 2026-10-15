-- COMMERCIAL_SITE_CRM_LINK_V1 / PHASE 1 - document-confirmed cross-check.
-- Runs against document_intelligence. Read-only.
--
-- Requires SELECT on confirmed_category_facts (role doc_worker / postgres).
-- The CRM runtime role crm_app has no grant on that table yet, so the
-- commercial API reads the CRM-side projection instead
-- (crm_procurement_category_opportunities.confirmed_at, written by
--  scripts/write_confirmed_base.py straight from these facts).

\pset footer off

SELECT 'CONFIRMED_DI_FACTS_PROCUREMENTS' AS metric, count(DISTINCT procurement_id)::bigint AS value
  FROM confirmed_category_facts
UNION ALL
SELECT 'CONFIRMED_DI_FACTS_CATEGORY_PAIRS', count(*)::bigint FROM (
  SELECT DISTINCT procurement_id, category_code FROM confirmed_category_facts
) cp
UNION ALL
SELECT 'CONFIRMED_DI_FACTS_ROWS', count(*)::bigint FROM confirmed_category_facts;

\echo --- confirmed facts per category ---
SELECT category_code, count(DISTINCT procurement_id) AS procurements, count(*) AS facts
  FROM confirmed_category_facts GROUP BY 1 ORDER BY 2 DESC;
