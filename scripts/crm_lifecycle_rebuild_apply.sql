-- CRM lifecycle rebuild (approved write plan). Runs in ONE transaction.
-- Default end-state: ROLLBACK (dry-run). Replace the final ROLLBACK with COMMIT
-- to apply.
--
-- Rules:
--   resolver: COMPLETED > AWARDED > COMMISSION > MAIN, COMPLETED terminal
--   true DIRECT_GOODS + AWARDED -> CLOSED ; object/embedded/design + AWARDED -> FOLLOW_UP_AWARDED
--   COMPLETED -> terminal
--   source_table / source_id are NEVER rewritten
--   NMCK: object-form and unknown-form full-NMCK rows -> NULL / NOT_AVAILABLE
--   CURRENT duplicates by (contract_number, category): loser -> SUPERSEDED (no DELETE)

\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE s7_active(contract_number text, t text);
COPY s7_active FROM '/tmp/s7_active.csv' WITH (FORMAT csv);
CREATE TEMP TABLE s7_inactive(contract_number text, t text);
COPY s7_inactive FROM '/tmp/s7_inactive.csv' WITH (FORMAT csv);
CREATE TEMP TABLE s7_all AS
SELECT contract_number, t FROM s7_active UNION ALL SELECT contract_number, t FROM s7_inactive;
CREATE TEMP TABLE s7_state AS
SELECT contract_number,
       CASE WHEN bool_or(t LIKE '%completed') THEN 'COMPLETED'
            WHEN bool_or(t LIKE '%awarded') THEN 'AWARDED'
            WHEN bool_or(t LIKE '%commission_work') THEN 'COMMISSION'
            ELSE 'MAIN' END AS s7_state
  FROM s7_all WHERE contract_number IS NOT NULL GROUP BY 1;

-- 1+2) sync lifecycle/result fields (NO source_table/source_id rewrite)
UPDATE crm_procurements p
   SET award_status = CASE s.s7_state
                        WHEN 'COMPLETED' THEN 'completed'
                        WHEN 'AWARDED' THEN 'awarded'
                        WHEN 'COMMISSION' THEN 'submission_closed_waiting_award'
                        ELSE p.award_status END,
       crm_stage = CASE s.s7_state
                     WHEN 'COMPLETED' THEN 'completed'
                     WHEN 'AWARDED' THEN 'razygranye'
                     WHEN 'COMMISSION' THEN 'commission'
                     ELSE p.crm_stage END,
       crm_updated_at = NOW()
  FROM s7_state s
 WHERE p.contract_number = s.contract_number
   AND (
        (s.s7_state='COMPLETED' AND lower(coalesce(p.award_status,'')) <> 'completed')
     OR (s.s7_state='AWARDED'   AND lower(coalesce(p.award_status,'')) NOT IN ('awarded','completed'))
     OR (s.s7_state='COMMISSION' AND lower(coalesce(p.award_status,'')) NOT IN ('submission_closed_waiting_award'))
   );

-- 3) form-aware lifecycle on CURRENT opportunities
UPDATE crm_procurement_category_opportunities o
   SET commercial_state = CASE
         WHEN s.s7_state='COMPLETED' THEN 'CLOSED'
         WHEN s.s7_state='AWARDED' AND o.procurement_form='DIRECT_GOODS_PURCHASE' THEN 'CLOSED'
         WHEN s.s7_state='AWARDED' THEN 'FOLLOW_UP_AWARDED'
         ELSE o.commercial_state END,
       updated_at = NOW()
  FROM crm_procurements p, s7_state s
 WHERE p.id = o.procurement_id AND p.contract_number = s.contract_number
   AND o.status='CURRENT'
   AND (
        (s.s7_state='COMPLETED' AND upper(coalesce(o.commercial_state,'')) NOT IN ('CLOSED','ARCHIVED','STALE_SOURCE','SUPPRESSED'))
     OR (s.s7_state='AWARDED' AND o.procurement_form='DIRECT_GOODS_PURCHASE' AND upper(coalesce(o.commercial_state,'')) <> 'CLOSED')
     OR (s.s7_state='AWARDED' AND coalesce(o.procurement_form,'') <> 'DIRECT_GOODS_PURCHASE' AND upper(coalesce(o.commercial_state,'')) <> 'FOLLOW_UP_AWARDED')
   );

-- 4) NMCK: object-form and unknown-form full-NMCK -> NULL / NOT_AVAILABLE
UPDATE crm_procurement_category_opportunities o
   SET expected_category_value = NULL,
       category_value_basis = 'NOT_AVAILABLE',
       updated_at = NOW()
  FROM crm_procurements p
 WHERE p.id = o.procurement_id AND o.status='CURRENT'
   AND o.expected_category_value IS NOT NULL AND p.initial_price IS NOT NULL
   AND o.expected_category_value = p.initial_price
   AND (o.procurement_form IN ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN')
        OR o.procurement_form IS NULL
        OR o.procurement_form IN ('UNKNOWN','WORKS_OTHER','SERVICES_OTHER'));

-- 5) dedup CURRENT by (contract_number, category): priority
--    confirmed_base > full medal lineage > correct form > higher id tie-break
WITH ranked AS (
  SELECT o.id,
         row_number() OVER (
           PARTITION BY p.contract_number, o.commercial_category_code
           ORDER BY (o.confirmed_base_medal IS NOT NULL) DESC,
                    (o.confirmed_base_score IS NOT NULL) DESC,
                    (o.current_effective_medal IS NOT NULL) DESC,
                    (o.procurement_form IN ('DIRECT_GOODS_PURCHASE','CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN')) DESC,
                    o.id DESC
         ) AS rn
    FROM crm_procurement_category_opportunities o
    JOIN crm_procurements p ON p.id = o.procurement_id
   WHERE o.status='CURRENT' AND p.contract_number IS NOT NULL
)
UPDATE crm_procurement_category_opportunities o
   SET status='SUPERSEDED', updated_at=NOW()
  FROM ranked r
 WHERE o.id = r.id AND r.rn > 1;

-- acceptance
CREATE TEMP TABLE opp AS
SELECT o.id, o.commercial_state, o.procurement_form, o.expected_category_value,
       p.initial_price, p.contract_number, s.s7_state, o.status
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id=o.procurement_id
  LEFT JOIN s7_state s ON s.contract_number=p.contract_number
 WHERE o.status='CURRENT';

SELECT
 (SELECT count(*) FROM opp WHERE s7_state='AWARDED' AND procurement_form='DIRECT_GOODS_PURCHASE' AND upper(coalesce(commercial_state,'')) NOT IN ('CLOSED')) AS TRUE_DIRECT_AWARDED_LEFT_ACTIVE,
 (SELECT count(*) FROM opp WHERE s7_state='AWARDED' AND procurement_form IN ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN') AND upper(coalesce(commercial_state,''))='CLOSED') AS OBJECT_AWARDED_WRONGLY_CLOSED,
 (SELECT count(*) FROM opp WHERE s7_state='COMPLETED' AND upper(coalesce(commercial_state,'')) NOT IN ('CLOSED','ARCHIVED','STALE_SOURCE','SUPPRESSED')) AS COMPLETED_LEFT_ACTIVE,
 (SELECT count(*) FROM opp WHERE procurement_form IN ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN') AND initial_price IS NOT NULL AND expected_category_value = initial_price) AS OBJECT_FORM_WITH_DIRECT_NMCK_VALUE,
 (SELECT count(*) FROM opp WHERE (procurement_form IS NULL OR procurement_form IN ('UNKNOWN','WORKS_OTHER','SERVICES_OTHER')) AND initial_price IS NOT NULL AND expected_category_value = initial_price) AS UNKNOWN_FORM_WITH_DIRECT_NMCK_VALUE,
 (SELECT count(*) FROM (SELECT p.contract_number, o.commercial_category_code FROM crm_procurement_category_opportunities o JOIN crm_procurements p ON p.id=o.procurement_id WHERE o.status='CURRENT' AND p.contract_number IS NOT NULL GROUP BY 1,2 HAVING count(*)>1) t) AS DUPLICATE_CURRENT_OPPORTUNITIES_BY_STABLE_ID_CATEGORY,
 (SELECT count(*) FROM opp WHERE s7_state='AWARDED' AND procurement_form IN ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN') AND upper(coalesce(commercial_state,''))='FOLLOW_UP_AWARDED') AS OBJECT_AWARDED_FOLLOW_UP;

ROLLBACK;   -- replace with COMMIT to apply
