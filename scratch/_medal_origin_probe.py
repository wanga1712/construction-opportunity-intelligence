"""Откуда взялась медаль: полная карточка возможности + подтверждение моделью."""
import json
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

PIDS = (459670, 459631)
kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(**kw)
try:
    for pid in PIDS:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM crm_procurement_category_opportunities
                   WHERE procurement_id = %s ORDER BY commercial_priority_score DESC NULLS LAST""",
                (pid,),
            )
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
        print("=== pid %s (%d возможностей) ===" % (pid, len(rows)))
        for raw in rows:
            row = dict(zip(cols, raw))
            keep = {
                "id": row.get("id"), "assessment_id": row.get("assessment_id"),
                "cat": row.get("commercial_category_code"), "sub": row.get("commercial_subcategory_code"),
                "track": row.get("opportunity_track"), "form": row.get("procurement_form"),
                "analysis_mode": row.get("analysis_mode"), "state": row.get("commercial_state"),
                "conf": row.get("category_confidence"),
                "value": row.get("expected_category_value"), "basis": row.get("category_value_basis"),
                "comm_score": row.get("commercial_priority_score"),
                "research_score": row.get("research_value_score"),
                "cand_initial": row.get("candidate_initial_score"),
                "cand_medal": row.get("candidate_medal"),
                "init_medal": row.get("candidate_initial_medal"),
                "init_prov": row.get("initial_medal_provenance"),
                "eff_medal": row.get("current_effective_medal"),
                "eff_reason": row.get("current_effective_reason"),
                "model": row.get("model_name"), "prompt": row.get("prompt_version"),
                "routing": row.get("routing_version"), "regver": row.get("registry_version"),
                "status": row.get("status"),
            }
            print("   " + json.dumps(keep, ensure_ascii=False, default=str))
        with conn.cursor() as cur:
            cur.execute("select table_name from information_schema.tables where table_schema='public' and table_name like '%assessment%'")
            tables = [r[0] for r in cur.fetchall()]
        print("   assessment tables: %s" % tables)
        for table in tables:
            try:
                with conn.cursor() as cur:
                    cur.execute("select column_name from information_schema.columns where table_name=%s", (table,))
                    table_cols = [r[0] for r in cur.fetchall()]
                    if "procurement_id" not in table_cols:
                        continue
                    cur.execute("select count(*) from %s where procurement_id = %%s" % table, (pid,))
                    count = cur.fetchone()[0]
                print("   %s: rows=%s cols=%s" % (table, count, table_cols[:12]))
            except Exception as exc:  # noqa: BLE001
                print("   %s: %s" % (table, exc))
finally:
    conn.close()
