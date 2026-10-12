-- Form-aware S7 lifecycle + NMCK acceptance (read-only).
-- Uses the REAL procurement_form from crm_procurement_category_opportunities,
-- not the legacy DIRECT_SUPPLY tag:
--   DIRECT_GOODS_PURCHASE + AWARDED  -> CLOSED
--   object forms  + AWARDED         -> FOLLOW_UP_AWARDED (commercially активна)
--   COMPLETED                       -> terminal
-- Targets: TRUE_DIRECT_AWARDED_LEFT_ACTIVE=0, COMPLETED_LEFT_ACTIVE=0,
--          OBJECT_AWARDED_WRONGLY_CLOSED=0,
--          OBJECT_FORM_WITH_DIRECT_NMCK_VALUE=0, TRUE_DIRECT_NMCK_LEAK=0

CREATE TEMP TABLE s7_active(contract_number text, t text);
COPY s7_active FROM '/tmp/s7_active.csv' WITH (FORMAT csv);
CREATE TEMP TABLE s7_inactive(contract_number text, t text);
COPY s7_inactive FROM '/tmp/s7_inactive.csv' WITH (FORMAT csv);
CREATE TEMP TABLE s7_all AS SELECT contract_number,t FROM s7_active UNION ALL SELECT contract_number,t FROM s7_inactive;
CREATE TEMP TABLE s7_state AS
SELECT contract_number, CASE WHEN bool_or(t LIKE '%completed') THEN 'COMPLETED'
                             WHEN bool_or(t LIKE '%awarded') THEN 'AWARDED'
                             WHEN bool_or(t LIKE '%commission_work') THEN 'COMMISSION'
                             ELSE 'MAIN' END AS s7_state
  FROM s7_all WHERE contract_number IS NOT NULL GROUP BY 1;

CREATE TEMP TABLE opp AS
SELECT o.id, o.commercial_state, o.procurement_form, o.opportunity_track,
       o.expected_category_value, p.initial_price, p.contract_number, s.s7_state
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id=o.procurement_id
  LEFT JOIN s7_state s ON s.contract_number=p.contract_number
 WHERE o.status='CURRENT';

SELECT
 (SELECT count(*) FROM opp WHERE s7_state='AWARDED' AND procurement_form='DIRECT_GOODS_PURCHASE'
    AND upper(coalesce(commercial_state,'')) NOT IN ('CLOSED')) AS TRUE_DIRECT_AWARDED_LEFT_ACTIVE,
 (SELECT count(*) FROM opp WHERE s7_state='AWARDED' AND procurement_form IN
    ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN')) AS OBJECT_AWARDED_FOLLOW_UP,
 (SELECT count(*) FROM opp WHERE s7_state='AWARDED' AND procurement_form IN
    ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN')
    AND upper(coalesce(commercial_state,''))='CLOSED') AS OBJECT_AWARDED_WRONGLY_CLOSED,
 (SELECT count(*) FROM opp WHERE s7_state='COMPLETED'
    AND upper(coalesce(commercial_state,'')) NOT IN ('CLOSED','ARCHIVED','STALE_SOURCE','SUPPRESSED')) AS COMPLETED_LEFT_ACTIVE;

SELECT
 count(*) FILTER (WHERE procurement_form='DIRECT_GOODS_PURCHASE') AS TRUE_DIRECT_GOODS_NMCK,
 count(*) FILTER (WHERE procurement_form IN ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN')) AS OBJECT_FORM_MISTRACK_NMCK,
 count(*) FILTER (WHERE procurement_form IS NULL OR procurement_form IN ('UNKNOWN','WORKS_OTHER','SERVICES_OTHER')) AS UNKNOWN_FORM_NMCK
FROM opp WHERE initial_price IS NOT NULL AND expected_category_value IS NOT NULL
  AND expected_category_value = initial_price;

SELECT
 (SELECT count(*) FROM opp WHERE procurement_form IN ('CONSTRUCTION_WORKS','DESIGN_AND_BUILD','DESIGN_EXPERTISE_AND_BUILD','DESIGN_ONLY','SURVEY_AND_DESIGN')
    AND initial_price IS NOT NULL AND expected_category_value = initial_price) AS OBJECT_FORM_WITH_DIRECT_NMCK_VALUE,
 (SELECT count(*) FROM opp WHERE procurement_form='DIRECT_GOODS_PURCHASE' AND s7_state='AWARDED'
    AND expected_category_value = initial_price) AS TRUE_DIRECT_NMCK_LEAK;
