#!/usr/bin/env python3
"""Read-only S13 count waterfall for analytics expert worksets."""
import json, os, sys
from pathlib import Path
root=Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit")); os.chdir(root); sys.path[:0]=[str(root), os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89")]
from dotenv import load_dotenv
load_dotenv(root/".env", override=True)
from src.services.db_bootstrap import connect_databases
_,_,db,_=connect_databases()
row=db.execute_query("""
WITH x AS (
 SELECT cp.*,
   ai.id IS NOT NULL AS has_ai,
   (ai.id IS NOT NULL AND upper(coalesce(ai.status,'')) NOT IN ('ERROR','FAILED')
    AND ai.normalized_result IS NOT NULL
    AND (ai.normalized_result ? 'business_scope_status' OR ai.normalized_result ? 'category_opportunities' OR ai.normalized_result ? 'candidate_level')) AS ai_valid,
   upper(coalesce(ai.normalized_result->>'business_scope_status','')) IN ('IN_PROFILE','OUT_OF_PROFILE') AS scope_usable,
   EXISTS(SELECT 1 FROM crm_procurement_category_opportunities o WHERE o.procurement_id=cp.id AND o.status='CURRENT') AS has_current_opp,
   EXISTS(SELECT 1 FROM crm_procurement_category_opportunities o WHERE o.procurement_id=cp.id AND o.status='CURRENT' AND o.commercial_state IN ('ACTIVE','FOLLOW_UP_AWARDED')) AS has_visible_opp,
   upper(coalesce(ai.status,'')) AS ai_status, ai.normalized_result
 FROM crm_procurements cp LEFT JOIN procurement_ai_assessments ai ON ai.procurement_id=cp.id AND ai.is_current=TRUE
), life AS (SELECT * FROM x WHERE crm_stage='torgi' AND award_status='submission_open' AND end_date>=CURRENT_DATE)
SELECT
 (SELECT count(*) FROM x WHERE crm_stage='torgi') crm_stage_total,
 (SELECT count(*) FROM x WHERE crm_stage='torgi' AND award_status='submission_open') submission_open,
 count(*) not_expired,
 count(*) FILTER(WHERE has_ai) with_current_ai,
 count(*) FILTER(WHERE ai_valid) ai_valid,
 count(*) FILTER(WHERE ai_valid AND scope_usable) scope_usable,
 count(*) FILTER(WHERE has_current_opp) with_current_opportunity,
 count(*) FILTER(WHERE has_visible_opp) with_visible_opportunity,
 count(*) FILTER(WHERE ai_valid AND scope_usable AND has_visible_opp) manager_visible,
 count(*) FILTER(WHERE NOT has_ai) hidden_unassessed,
 count(*) FILTER(WHERE has_ai AND ai_status IN ('ERROR','FAILED')) hidden_failed,
 count(*) FILTER(WHERE has_ai AND ai_status NOT IN ('ERROR','FAILED') AND normalized_result IS NULL) hidden_incomplete,
 count(*) FILTER(WHERE has_ai AND ai_status NOT IN ('ERROR','FAILED') AND normalized_result IS NOT NULL AND NOT ai_valid) hidden_malformed,
 count(*) FILTER(WHERE ai_valid AND NOT scope_usable) hidden_scope_unknown,
 count(*) FILTER(WHERE ai_valid AND scope_usable AND NOT has_visible_opp) hidden_no_visible_opportunity
FROM life
""")[0]
row["source_breakdown"]=db.execute_query("""SELECT source_table,count(*) n FROM crm_procurements WHERE crm_stage='torgi' AND award_status='submission_open' AND end_date>=CURRENT_DATE GROUP BY source_table ORDER BY n DESC""")
row["open_44_fz"]=sum(r["n"] for r in row["source_breakdown"] if "44" in (r["source_table"] or ""))
row["open_223_fz"]=sum(r["n"] for r in row["source_breakdown"] if "223" in (r["source_table"] or ""))
row["real_commission_total"]=db.execute_scalar("SELECT count(*) FROM crm_procurements WHERE crm_stage='torgi' AND award_status IN ('submission_closed_waiting_award','award_not_found')")
row["real_awarded_total"]=db.execute_scalar("SELECT count(*) FROM crm_procurements WHERE crm_stage='razygranye'")
print(json.dumps(row,ensure_ascii=False,default=str,indent=2))
