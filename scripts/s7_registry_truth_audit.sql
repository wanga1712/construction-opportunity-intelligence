-- S7 registry truth audit (read-only).
-- Requires /tmp/s7_active.csv and /tmp/s7_inactive.csv exported from S7:
--   active   = reestr_contract_{44,223}_fz (+_commission_work) + reestr_contract_615_pp
--   inactive = reestr_contract_{44,223}_fz_awarded / _completed
-- Run inside the CRM database (contract_number is the sync key).
--
-- Canonical table priority (src/services/tender_registry_query.table_priority):
--   main 40 > commission_work 35 > unclear/unknown 34 > awarded 25 > completed 20
-- => a contract still present in "main" is treated as ACTIVE even if it also
--    exists in "awarded"/"completed".

CREATE TEMP TABLE s7_active(contract_number text, t text);
COPY s7_active FROM '/tmp/s7_active.csv' WITH (FORMAT csv);
CREATE TEMP TABLE s7_inactive(contract_number text, t text);
COPY s7_inactive FROM '/tmp/s7_inactive.csv' WITH (FORMAT csv);

CREATE TEMP TABLE s7_all AS
SELECT contract_number, t FROM s7_active UNION ALL SELECT contract_number, t FROM s7_inactive;

CREATE TEMP TABLE s7_flags AS
SELECT contract_number,
       bool_or(t IN ('reestr_contract_44_fz','reestr_contract_223_fz','reestr_contract_615_pp')) AS in_main,
       bool_or(t LIKE '%commission_work') AS in_comm,
       bool_or(t LIKE '%awarded') AS in_awarded,
       bool_or(t LIKE '%completed') AS in_completed
  FROM s7_all WHERE contract_number IS NOT NULL GROUP BY 1;

-- 1) physical-table conflicts
SELECT count(*) FILTER (WHERE in_main AND in_awarded)    AS in_main_and_awarded,
       count(*) FILTER (WHERE in_main AND in_completed)  AS in_main_and_completed,
       count(*) FILTER (WHERE in_comm AND in_awarded)    AS in_commission_and_awarded,
       count(*)                                          AS distinct_contracts
  FROM s7_flags;

-- 2) canonical table distribution
SELECT CASE WHEN in_main THEN 'MAIN' WHEN in_comm THEN 'COMMISSION'
            WHEN in_awarded THEN 'AWARDED' WHEN in_completed THEN 'COMPLETED'
            ELSE 'OTHER' END AS canonical, count(*)
  FROM s7_flags GROUP BY 1 ORDER BY 2 DESC;

-- 3) CRM source_table class vs S7 canonical
SELECT count(*) AS crm_source_table_mismatch
  FROM crm_procurements p JOIN s7_flags f ON f.contract_number = p.contract_number
 WHERE (CASE WHEN p.source_table LIKE '%awarded' THEN 'AWARDED'
             WHEN p.source_table LIKE '%completed' THEN 'COMPLETED'
             WHEN p.source_table LIKE '%commission_work' THEN 'COMMISSION'
             ELSE 'MAIN' END)
       <> (CASE WHEN f.in_main THEN 'MAIN' WHEN f.in_comm THEN 'COMMISSION'
                WHEN f.in_awarded THEN 'AWARDED' WHEN f.in_completed THEN 'COMPLETED'
                ELSE 'OTHER' END);

-- 4) awarded DIRECT CURRENT opportunities vs S7 reality
SELECT count(*) AS awarded_direct_current,
       count(*) FILTER (WHERE f.in_main)                      AS still_in_main,
       count(*) FILTER (WHERE f.in_awarded AND NOT f.in_main) AS only_awarded,
       count(*) FILTER (WHERE f.in_completed AND NOT f.in_main) AS only_completed,
       count(*) FILTER (WHERE f.contract_number IS NULL)      AS not_on_s7
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id = o.procurement_id
  LEFT JOIN s7_flags f ON f.contract_number = p.contract_number
 WHERE o.status='CURRENT' AND lower(coalesce(p.award_status,''))='awarded';
