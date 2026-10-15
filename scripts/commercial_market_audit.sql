-- COMMERCIAL_SITE_CRM_LINK_V1 / PHASE 1 - MARKET TRUTH AUDIT (read-only, no counters)
--
-- Unit of every KPI: DISTINCT procurement_id. Every number is computed from
-- stored production state; nothing is hardcoded.
--
-- LIVE MARKET authority (already used by the deployment dashboards,
-- deploy/s13_dashboard3.py::heavy):
--   source_lifecycle = 'OPEN'    -> live tender            (admission_state='ELIGIBLE')
--   source_lifecycle = 'AWARDED' -> follow-up object/project (admission_state='ELIGIBLE')
-- Awarded DIRECT goods are kept out of the live market by the canonical
-- admission policy (admission_reason='AWARDED_DIRECT_GOODS'), so
-- AWARDED_DIRECT_IN_LIVE_MARKET is 0 by construction and is asserted below.
--
-- Run on S13:  bash scripts/run_commercial_market_audit.sh [--di]
-- Whole script is SELECT-only (no DDL, no DML).

\pset footer off

\echo === 0. CANONICAL ADMISSION POLICY (what the gate actually stored) ===
SELECT source_lifecycle, admission_state, coalesce(admission_reason, '-') AS reason,
       count(DISTINCT procurement_id) AS procurements
  FROM crm_procurement_scope_authority
 WHERE source_lifecycle IN ('OPEN','AWARDED')
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC;

CREATE TEMP VIEW audit_opportunity AS
SELECT procurement_id,
       bool_or(opportunity_track = 'DIRECT_SUPPLY')                                     AS has_direct_supply,
       bool_or(opportunity_track IN ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT',
                                     'DESIGN_INFLUENCE'))                                AS has_project_embedded,
       bool_or(opportunity_track IN ('DIRECT_SUPPLY','EMBEDDED_MATERIAL',
                                     'DESIGN_REQUIREMENT','DESIGN_INFLUENCE'))           AS has_commerce,
       bool_or(opportunity_track = 'NO_COMMERCIAL_ENTRY')                                AS has_no_entry,
       bool_or(commercial_state = 'FOLLOW_UP_AWARDED')                                   AS has_followup,
       bool_or(confirmed_at IS NOT NULL)                                                 AS has_confirmed,
       max(CASE current_effective_medal
             WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3 WHEN 'BRONZE' THEN 2
             WHEN 'WOOD' THEN 1 ELSE 0 END)                                              AS best_medal_rank
  FROM crm_procurement_category_opportunities
 WHERE status = 'CURRENT'
 GROUP BY procurement_id;

-- Commercial universe = live market segments (disjoint by admission state).
CREATE TEMP VIEW audit_market AS
SELECT sa.procurement_id,
       CASE WHEN sa.source_lifecycle = 'OPEN' THEN 'OPEN' ELSE 'AWARDED_FOLLOWUP' END AS segment,
       sa.source_lifecycle,
       sa.procurement_scope_type,
       sa.admission_state,
       coalesce(o.has_direct_supply, false)    AS has_direct_supply,
       coalesce(o.has_project_embedded, false) AS has_project_embedded,
       coalesce(o.has_commerce, false)         AS has_commerce,
       coalesce(o.has_no_entry, false)         AS has_no_entry,
       coalesce(o.has_followup, false)         AS has_followup,
       coalesce(o.has_confirmed, false)        AS has_confirmed,
       coalesce(o.best_medal_rank, 0)          AS best_medal_rank
  FROM crm_procurement_scope_authority sa
  LEFT JOIN audit_opportunity o ON o.procurement_id = sa.procurement_id
 WHERE sa.source_lifecycle IN ('OPEN','AWARDED')
   AND sa.admission_state = 'ELIGIBLE';

\echo === 1. HEADLINE (DISTINCT procurement_id) ===
SELECT 'COMMERCIAL_UNIVERSE_DISTINCT' AS metric, count(*)::bigint AS value FROM audit_market
UNION ALL SELECT 'OPEN_DISTINCT',             count(*) FROM audit_market WHERE segment = 'OPEN'
UNION ALL SELECT 'AWARDED_FOLLOWUP_DISTINCT', count(*) FROM audit_market WHERE segment = 'AWARDED_FOLLOWUP'
UNION ALL SELECT 'WITH_COMMERCE',             count(*) FROM audit_market WHERE has_commerce
UNION ALL SELECT 'WITHOUT_COMMERCE',          count(*) FROM audit_market WHERE NOT has_commerce
UNION ALL SELECT 'DIRECT_SUPPLY',             count(*) FROM audit_market WHERE has_direct_supply
UNION ALL SELECT 'PROJECT_EMBEDDED',          count(*) FROM audit_market WHERE has_project_embedded
UNION ALL SELECT 'CONFIRMED',                 count(*) FROM audit_market WHERE has_confirmed
UNION ALL SELECT 'PRELIMINARY_ONLY',          count(*) FROM audit_market WHERE NOT has_confirmed
UNION ALL SELECT 'AWARDED_DIRECT_IN_LIVE_MARKET',
                 count(*) FROM audit_market
                  WHERE segment = 'AWARDED_FOLLOWUP' AND procurement_scope_type = 'DIRECT_GOODS'
ORDER BY 1;

\echo === 2. INVARIANTS (all must be true) ===
SELECT
  (SELECT count(*) FROM audit_market WHERE segment = 'OPEN')
    + (SELECT count(*) FROM audit_market WHERE segment = 'AWARDED_FOLLOWUP')
      = (SELECT count(*) FROM audit_market)                        AS open_plus_awarded_eq_universe,
  (SELECT count(*) FROM audit_market WHERE has_commerce)
    + (SELECT count(*) FROM audit_market WHERE NOT has_commerce)
      = (SELECT count(*) FROM audit_market)                        AS commerce_split_eq_universe,
  (SELECT count(*) FROM audit_market
    WHERE segment = 'AWARDED_FOLLOWUP' AND procurement_scope_type = 'DIRECT_GOODS') = 0
                                                                   AS awarded_direct_zero,
  (SELECT count(*) FROM audit_market WHERE has_confirmed)
    + (SELECT count(*) FROM audit_market WHERE NOT has_confirmed)
      = (SELECT count(*) FROM audit_market)                        AS confirmed_split_eq_universe;

\echo === 3. SEGMENT x SCOPE TYPE ===
SELECT segment, procurement_scope_type, count(*) AS procurements
  FROM audit_market GROUP BY 1, 2 ORDER BY 1, 3 DESC;

\echo === 4. SEGMENT x COMMERCE / CONFIRMATION ===
SELECT segment,
       count(*)                                     AS universe,
       count(*) FILTER (WHERE has_commerce)         AS with_commerce,
       count(*) FILTER (WHERE NOT has_commerce)     AS without_commerce,
       count(*) FILTER (WHERE has_direct_supply)    AS direct_supply,
       count(*) FILTER (WHERE has_project_embedded) AS project_embedded,
       count(*) FILTER (WHERE has_confirmed)        AS confirmed,
       count(*) FILTER (WHERE NOT has_confirmed)    AS preliminary_only
  FROM audit_market GROUP BY 1 ORDER BY 1;

\echo === 5. WITHOUT_COMMERCE DECOMPOSITION (assessed verdict vs not yet assessed) ===
SELECT count(*)                                           AS without_commerce,
       count(*) FILTER (WHERE has_no_entry)               AS explicit_no_commercial_entry,
       count(*) FILTER (WHERE NOT has_no_entry)           AS no_current_commerce_verdict
  FROM audit_market WHERE NOT has_commerce;

\echo === 6. BREAKDOWN BY BEST CURRENT MEDAL ===
SELECT CASE best_medal_rank WHEN 4 THEN 'GOLD' WHEN 3 THEN 'SILVER' WHEN 2 THEN 'BRONZE'
                            WHEN 1 THEN 'WOOD' ELSE 'UNASSESSED' END AS best_medal,
       segment, count(*) AS procurements
  FROM audit_market GROUP BY 1, 2 ORDER BY 1, 2;

\echo === 7. BREAKDOWN BY COMMERCIAL CATEGORY (current rows inside the universe) ===
SELECT o.commercial_category_code AS category_code,
       count(DISTINCT o.procurement_id) AS procurements,
       count(DISTINCT o.procurement_id) FILTER (WHERE o.confirmed_at IS NOT NULL) AS confirmed,
       count(DISTINCT o.procurement_id) FILTER (WHERE o.opportunity_track = 'DIRECT_SUPPLY')
         AS direct_supply,
       count(DISTINCT o.procurement_id) FILTER (WHERE m.segment = 'AWARDED_FOLLOWUP')
         AS awarded_followup
  FROM crm_procurement_category_opportunities o
  JOIN audit_market m ON m.procurement_id = o.procurement_id
 WHERE o.status = 'CURRENT'
 GROUP BY 1 ORDER BY 2 DESC;

\echo === 8. BREAKDOWN BY OPPORTUNITY TRACK x COMMERCIAL STATE (current rows) ===
SELECT o.opportunity_track, o.commercial_state,
       count(DISTINCT o.procurement_id) AS procurements
  FROM crm_procurement_category_opportunities o
  JOIN audit_market m ON m.procurement_id = o.procurement_id
 WHERE o.status = 'CURRENT'
 GROUP BY 1, 2 ORDER BY 3 DESC;

\echo === 9. ROUTING-CONTOUR CONTEXT (routed rows inside universe lifecycles, any admission) ===
SELECT count(DISTINCT sa.procurement_id) AS routed_in_universe_lifecycles
  FROM crm_procurement_scope_authority sa
 WHERE sa.source_lifecycle IN ('OPEN','AWARDED')
   AND EXISTS (SELECT 1 FROM crm_procurement_category_opportunities o
                WHERE o.procurement_id = sa.procurement_id AND o.status = 'CURRENT');

\echo === 10. CONFIRMED CROSS-CHECK (CRM projection side of the universe) ===
SELECT count(*) AS confirmed_crm_projection FROM audit_market WHERE has_confirmed;
