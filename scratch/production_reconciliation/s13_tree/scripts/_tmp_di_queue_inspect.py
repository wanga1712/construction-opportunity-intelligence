#!/usr/bin/env python3
import os
import sys

sys.path[:0] = ["/opt/CRM_Streamlit"]
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
import psycopg2

BATCH = [6406, 20732, 17285, 21599, 21500]
con = psycopg2.connect(
    host="127.0.0.1",
    dbname="document_intelligence",
    user=os.getenv("CRM_DB_USER"),
    password=os.getenv("CRM_DB_PASSWORD"),
)
cur = con.cursor()
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name='document_processing_queue' ORDER BY ordinal_position"
)
print("cols", [r[0] for r in cur.fetchall()])
cur.execute("SELECT status, count(*) FROM document_processing_queue GROUP BY 1 ORDER BY 1")
print("all", cur.fetchall())
cur.execute(
    "SELECT * FROM document_processing_queue WHERE procurement_id = ANY(%s) ORDER BY procurement_id",
    (BATCH,),
)
cols = [d[0] for d in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()]
for r in rows:
    keep = {
        k: r.get(k)
        for k in cols
        if k
        in (
            "id",
            "procurement_id",
            "status",
            "queue_lane",
            "lane",
            "priority",
            "source_table",
            "pipeline_generation",
            "created_at",
            "started_at",
            "finished_at",
            "worker_id",
            "error",
            "last_error",
            "research_depth",
        )
    }
    print(keep)
# recent activity any
cur.execute(
    "SELECT status, count(*) FROM document_processing_queue WHERE created_at >= now() - interval '2 hours' GROUP BY 1"
)
print("recent2h", cur.fetchall())
con.close()
