-- LAYOUT_TEMPLATE_COVERAGE_V1 / step 1: document-level problem inventory.
-- Counts DOCUMENTS (not facts/rows), as agreed.
-- Run part A in document_intelligence, part B in crm.

-- A) document_intelligence
WITH ent AS (
  SELECT source_document_id,
         bool_or(layout_status='UNSUPPORTED_LAYOUT') AS unsupported,
         bool_or(layout_status='INCONSISTENT_LAYOUT') AS inconsistent,
         count(*) AS facts
    FROM structured_entities
   WHERE extractor_version='EMBEDDED_EXTRACTOR_V1' AND source_document_id IS NOT NULL
   GROUP BY 1
),
outc AS (
  SELECT source_document_id, bool_or(outcome='NO_FACTS') AS no_facts
    FROM document_extraction_outcomes WHERE source_document_id IS NOT NULL GROUP BY 1
),
doc AS (
  SELECT f.id AS doc_id, f.procurement_id,
         coalesce(e.unsupported,false) AS unsupported,
         coalesce(e.inconsistent,false) AS inconsistent,
         coalesce(o.no_facts,false) AS no_facts
    FROM document_files f
    LEFT JOIN ent e ON e.source_document_id=f.id
    LEFT JOIN outc o ON o.source_document_id=f.id
   WHERE e.source_document_id IS NOT NULL OR o.source_document_id IS NOT NULL
)
SELECT count(*) AS documents_seen,
       count(*) FILTER (WHERE unsupported OR inconsistent OR no_facts) AS problem_documents,
       count(*) FILTER (WHERE unsupported)    AS unsupported_documents,
       count(*) FILTER (WHERE inconsistent)   AS inconsistent_documents,
       count(*) FILTER (WHERE no_facts)       AS no_facts_documents,
       count(DISTINCT procurement_id) FILTER (WHERE unsupported OR inconsistent OR no_facts) AS problem_procurements
  FROM doc;

-- B) export the affected procurements, then count CURRENT opportunities in crm:
--   \copy (SELECT DISTINCT f.procurement_id FROM document_files f
--           WHERE f.id IN (SELECT source_document_id FROM document_extraction_outcomes
--                          WHERE outcome='NO_FACTS' AND source_document_id IS NOT NULL)
--              OR f.id IN (SELECT source_document_id FROM structured_entities
--                          WHERE extractor_version='EMBEDDED_EXTRACTOR_V1'
--                            AND layout_status IN ('UNSUPPORTED_LAYOUT','INCONSISTENT_LAYOUT')
--                            AND source_document_id IS NOT NULL)) TO '/tmp/problem_pids.txt'
--   CREATE TEMP TABLE pp(pid bigint); COPY pp FROM '/tmp/problem_pids.txt';
--   SELECT count(DISTINCT o.id), count(DISTINCT o.procurement_id)
--     FROM crm_procurement_category_opportunities o JOIN pp ON pp.pid=o.procurement_id
--    WHERE o.status='CURRENT';
