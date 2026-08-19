#!/usr/bin/env python3
"""Read-only dry-run: torgi visibility before/after Phase 4 gate."""
from __future__ import annotations

import json
import time

# Run on S13 with CRM env loaded
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)

from src.services.db_bootstrap import connect_databases
from src.services.torgi_publication import torgi_publication_sql_filters

_, _, crm_db, _ = connect_databases()
pub = torgi_publication_sql_filters()

OLD_SQL = """
SELECT count(DISTINCT cp.id) AS c
FROM crm_procurements cp
WHERE cp.crm_stage = 'torgi'
  AND cp.award_status = 'submission_open'
  AND cp.end_date >= CURRENT_DATE
"""

NEW_SQL = f"""
SELECT count(DISTINCT cp.id) AS c
FROM crm_procurements cp
WHERE cp.crm_stage = 'torgi'
  AND cp.award_status = 'submission_open'
  AND cp.end_date >= CURRENT_DATE
  {pub}
"""

BREAKDOWN_SQL = f"""
WITH base AS (
  SELECT cp.id
  FROM crm_procurements cp
  WHERE cp.crm_stage = 'torgi'
    AND cp.award_status = 'submission_open'
    AND cp.end_date >= CURRENT_DATE
),
assessed AS (
  SELECT b.id,
    CASE
      WHEN ai.id IS NULL THEN 'UNASSESSED'
      WHEN UPPER(COALESCE(ai.status,'')) IN ('ERROR','FAILED') THEN 'FAILED'
      WHEN ai.normalized_result IS NULL THEN 'INCOMPLETE'
      WHEN NOT (
        ai.normalized_result ? 'business_scope_status'
        OR ai.normalized_result ? 'category_opportunities'
        OR ai.normalized_result ? 'candidate_level'
      ) THEN 'MALFORMED'
      ELSE 'OK'
    END AS assess_bucket
  FROM base b
  LEFT JOIN procurement_ai_assessments ai
    ON ai.procurement_id = b.id AND ai.is_current = TRUE
),
with_opp AS (
  SELECT a.id, a.assess_bucket,
    EXISTS (
      SELECT 1 FROM crm_procurement_category_opportunities o
      WHERE o.procurement_id = a.id
        AND o.status = 'CURRENT'
        AND o.commercial_state IN ('ACTIVE','FOLLOW_UP_AWARDED')
    ) AS has_vis_opp
  FROM assessed a
)
SELECT
  count(*) FILTER (WHERE assess_bucket = 'UNASSESSED') AS hidden_unassessed,
  count(*) FILTER (WHERE assess_bucket = 'FAILED') AS hidden_failed,
  count(*) FILTER (WHERE assess_bucket = 'INCOMPLETE') AS hidden_incomplete,
  count(*) FILTER (WHERE assess_bucket = 'MALFORMED') AS hidden_malformed,
  count(*) FILTER (WHERE assess_bucket = 'OK' AND NOT has_vis_opp) AS hidden_no_opp,
  count(*) FILTER (WHERE assess_bucket = 'OK' AND has_vis_opp) AS remaining,
  count(*) AS total_base
FROM with_opp
"""

t0 = time.perf_counter()
before = int(crm_db.execute_scalar(OLD_SQL) or 0)
t1 = time.perf_counter()
after = int(crm_db.execute_scalar(NEW_SQL) or 0)
t2 = time.perf_counter()
bd = crm_db.execute_query(BREAKDOWN_SQL)[0]
t3 = time.perf_counter()

out = {
    "TORGI_VISIBLE_BEFORE": before,
    "TORGI_VISIBLE_AFTER": after,
    "HIDDEN_TOTAL": before - after,
    "HIDDEN_UNASSESSED": int(bd["hidden_unassessed"]),
    "HIDDEN_FAILED": int(bd["hidden_failed"]),
    "HIDDEN_INCOMPLETE": int(bd["hidden_incomplete"]),
    "HIDDEN_MALFORMED": int(bd["hidden_malformed"]),
    "HIDDEN_NO_VISIBLE_OPPORTUNITY": int(bd["hidden_no_opp"]),
    "REMAINING_ASSESSED": int(bd["remaining"]),
    "PERCENT_REMOVED": round(100.0 * (before - after) / before, 2) if before else 0,
    "TORGI_QUERY_MS_BEFORE": round((t1 - t0) * 1000, 1),
    "TORGI_QUERY_MS_AFTER": round((t2 - t1) * 1000, 1),
}
print(json.dumps(out, indent=2))
