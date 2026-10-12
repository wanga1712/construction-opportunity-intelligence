import os
import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

import psycopg2
from psycopg2.extras import RealDictCursor
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

conn = psycopg2.connect(**require_crm_db_connect_kwargs())
with conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("""
        SELECT COUNT(*) AS total_pco,
               COUNT(candidate_medal) AS with_candidate_medal,
               COUNT(confirmed_base_medal) AS with_confirmed_medal
        FROM crm_procurement_category_opportunities
    """)
    print("crm_procurement_category_opportunities stats:", cur.fetchone())

    cur.execute("""
        SELECT COUNT(*) AS total_ai,
               COUNT(proposed_level) AS with_proposed_level
        FROM procurement_ai_assessments
    """)
    print("procurement_ai_assessments stats:", cur.fetchone())
conn.close()
