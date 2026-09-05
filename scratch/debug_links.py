import sys
sys.path.append("/opt/CRM_Streamlit_rescue")
sys.path.append("/opt/pythonProject89")

import psycopg2
import psycopg2.extras
from src.services.commercial_routing_v3.document_links import resolve_document_links

conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

for pid in [14, 15, 16, 82]:
    cur.execute("SELECT source_table, source_id, contract_number FROM crm_procurements WHERE id = %s", (pid,))
    p_fact = cur.fetchone()
    if p_fact:
        print(f"PID={pid}: source_table={p_fact['source_table']}, source_id={p_fact['source_id']}, contract_number={p_fact['contract_number']}")
        res = resolve_document_links(
            source_table=str(p_fact.get("source_table") or ""),
            source_id=p_fact.get("source_id"),
            contract_number=p_fact.get("contract_number"),
        )
        print("  Links resolved:", len(res.get("links") or []))
        if res.get("error"):
            print("  Error:", res["error"])
    else:
        print(f"PID={pid} not found in crm_procurements")
conn.close()
