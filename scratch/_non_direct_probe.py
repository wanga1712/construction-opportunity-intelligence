"""Найти закупку в режиме «в составе работ/объект» для проверки неизменности карточки."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(**kw)
try:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT q.procurement_id, q.procurement_scope_type, p.contract_number
               FROM crm_procurement_scope_authority q
               JOIN crm_procurements p ON p.id = q.procurement_id
               WHERE q.procurement_scope_type <> 'DIRECT_GOODS'
                 AND q.admission_state = 'ELIGIBLE'
               ORDER BY q.procurement_id DESC LIMIT 5"""
        )
        for row in cur.fetchall():
            print("pid=%s scope=%s number=%s" % row)
        cur.execute(
            """SELECT o.procurement_id, o.opportunity_track, count(*)
               FROM crm_procurement_category_opportunities o
               WHERE o.opportunity_track = 'EMBEDDED_MATERIAL'
               GROUP BY 1,2 HAVING count(*) >= 3 ORDER BY 1 DESC LIMIT 5"""
        )
        print("--- embedded examples ---")
        for row in cur.fetchall():
            print("pid=%s track=%s opps=%s" % row)
        cur.execute("select id, contract_number from crm_procurements where contract_number='0351100008926000151'")
        print("--- control road procurement ---", cur.fetchall())
finally:
    conn.close()
