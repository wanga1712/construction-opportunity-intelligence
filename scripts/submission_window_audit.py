#!/usr/bin/env python3
"""Read-only production waterfall for the two-day submission window."""
import json, os, sys
from datetime import date
from pathlib import Path
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
root=Path(os.environ.get("CRM_APP_ROOT","/opt/CRM_Streamlit")); os.chdir(root)
sys.path[:0]=[str(root),os.environ.get("CRM_SOURCE_ROOT","/opt/pythonProject89")]
load_dotenv(root/".env",override=True)
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

def main():
 c=psycopg2.connect(**require_crm_db_connect_kwargs()); c.set_session(readonly=True,autocommit=True)
 with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as q:
  q.execute("""SELECT count(*) before,
   count(*) FILTER(WHERE end_date=CURRENT_DATE) d0,
   count(*) FILTER(WHERE end_date=CURRENT_DATE+1) d1,
   count(*) FILTER(WHERE end_date>=CURRENT_DATE+2) d2,
   count(*) FILTER(WHERE end_date=CURRENT_DATE AND source_table ILIKE '%%44%%') d0_44,
   count(*) FILTER(WHERE end_date=CURRENT_DATE AND source_table ILIKE '%%223%%') d0_223
   FROM crm_procurements WHERE crm_stage='torgi' AND award_status='submission_open' AND end_date>=CURRENT_DATE"""); out=dict(q.fetchone())
  q.execute("""SELECT source_table,count(*) n FROM crm_procurements WHERE crm_stage='torgi'
   AND award_status='submission_open' AND end_date=CURRENT_DATE GROUP BY 1 ORDER BY 2 DESC"""); out['d0_sources']=[dict(x) for x in q.fetchall()]
  q.execute("""SELECT
   count(*) FILTER(WHERE ai.id IS NULL) unassessed_before,
   count(*) FILTER(WHERE cp.end_date>=CURRENT_DATE+2 AND ai.id IS NULL) unassessed_after,
   count(*) FILTER(WHERE cp.end_date>=CURRENT_DATE+2) all_after
   FROM crm_procurements cp LEFT JOIN procurement_ai_assessments ai ON ai.procurement_id=cp.id AND ai.is_current
   WHERE cp.crm_stage='torgi' AND cp.award_status='submission_open' AND cp.end_date>=CURRENT_DATE"""); out.update(dict(q.fetchone()))
 print(json.dumps(out,ensure_ascii=False,default=str,indent=2))
if __name__=='__main__': main()
