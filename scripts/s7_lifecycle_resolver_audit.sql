-- Unified S7 lifecycle resolver + read-only CRM sync projection.
-- Resolver priority (per approved plan): COMPLETED > AWARDED > COMMISSION > MAIN.
-- unclear/nodates never override a concrete state.
-- Requires /tmp/s7_active.csv and /tmp/s7_inactive.csv (S7 snapshot export).

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

-- 1) resolved state distribution
SELECT s7_state, count(*) FROM s7_state GROUP BY 1 ORDER BY 2 DESC;

-- 2) CRM rows whose state would change (sync target fields only)
SELECT count(*) AS crm_rows_matched,
       count(*) FILTER (WHERE s.s7_state='COMPLETED' AND lower(coalesce(p.award_status,'')) NOT IN ('completed')) AS would_set_completed,
       count(*) FILTER (WHERE s.s7_state='AWARDED'   AND lower(coalesce(p.award_status,'')) NOT IN ('awarded'))   AS would_set_awarded,
       count(*) FILTER (WHERE s.s7_state='MAIN'      AND lower(coalesce(p.award_status,'')) IN ('awarded','completed')) AS would_reopen_to_main,
       count(*) FILTER (WHERE s.s7_state='COMMISSION') AS commission_rows
  FROM crm_procurements p JOIN s7_state s ON s.contract_number = p.contract_number;

-- 3) CURRENT opportunities after the corrected lifecycle (projection only)
SELECT count(*) AS current_opps,
       count(*) FILTER (WHERE s.s7_state='COMPLETED') AS terminal_completed,
       count(*) FILTER (WHERE s.s7_state='AWARDED')   AS awarded_state,
       count(*) FILTER (WHERE s.s7_state='MAIN')      AS still_open,
       count(*) FILTER (WHERE s.contract_number IS NULL) AS not_on_s7
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id=o.procurement_id
  LEFT JOIN s7_state s ON s.contract_number=p.contract_number
 WHERE o.status='CURRENT';
