#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import os, sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from dotenv import load_dotenv
load_dotenv('/opt/CRM_Streamlit/.env')
from src.services.db_bootstrap import connect_databases
from src.ui.components.analytics_v2.tabs import _stage_workset_ids
from src.services.annotation_state_service import count_annotation_states_sql, annotation_filter_sql_clause

_, _, crm_db, _ = connect_databases()
workset_ids = _stage_workset_ids("torgi")

def _scope_sql_expr():
    return "COALESCE(ea.payload ->> 'expert_category_scope', ea.payload -> 'expert_category_scope' ->> 'verdict')"

def filter_workset_ids_sql(procurement_ids: list[int], selected_review: str, crm_db) -> list[int]:
    if not procurement_ids or selected_review == "ALL":
        return procurement_ids
    scope_expr = _scope_sql_expr()
    if selected_review == "UNREVIEWED":
        sql = f"""
            SELECT p_id FROM unnest(%s::bigint[]) AS p_id
            WHERE p_id NOT IN (
                SELECT ea.procurement_id 
                FROM crm_v3_expert_annotations ea
                WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s)
                  AND (
                    ({scope_expr} IS NOT NULL AND {scope_expr} != '')
                    OR (({scope_expr} IS NULL OR {scope_expr} = '') AND (
                      ea.payload ->> 'expert_commercial_verdict' = 'NO_COMMERCIAL_ENTRY'
                      OR ea.payload ->> 'expert_scope_verdict' = 'OUT_OF_PROFILE'
                      OR ea.payload ->> 'expert_medal' = 'NCE'
                    ))
                  )
            )
        """
        rows = crm_db.execute_query(sql, (procurement_ids, procurement_ids))
    elif selected_review == "REVIEWED":
        sql = f"""
            SELECT ea.procurement_id 
            FROM crm_v3_expert_annotations ea
            WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s)
              AND (
                ({scope_expr} IS NOT NULL AND {scope_expr} != '')
                OR (({scope_expr} IS NULL OR {scope_expr} = '') AND (
                  ea.payload ->> 'expert_commercial_verdict' = 'NO_COMMERCIAL_ENTRY'
                  OR ea.payload ->> 'expert_scope_verdict' = 'OUT_OF_PROFILE'
                  OR ea.payload ->> 'expert_medal' = 'NCE'
                ))
              )
        """
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == "OUT_OF_CATEGORY":
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'OUT_OF_CATEGORY'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == "IN_CATEGORY":
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'IN_CATEGORY'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == "UNCERTAIN":
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'UNCERTAIN'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == "COMMERCIAL":
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND ea.payload ->> 'expert_commercial_entry' = 'COMMERCIAL'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == "NON_COMMERCIAL":
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND ea.payload ->> 'expert_commercial_entry' = 'NON_COMMERCIAL'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == "LEGACY_NOT_INTERESTING":
        sql = f"""
            SELECT ea.procurement_id FROM crm_v3_expert_annotations ea 
            WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) 
              AND ({scope_expr} IS NULL OR {scope_expr} = '')
              AND (
                ea.payload ->> 'expert_commercial_verdict' = 'NO_COMMERCIAL_ENTRY'
                OR ea.payload ->> 'expert_scope_verdict' = 'OUT_OF_PROFILE'
                OR ea.payload ->> 'expert_medal' = 'NCE'
              )
        """
        rows = crm_db.execute_query(sql, (procurement_ids,))
    else:
        rows = []
    filtered = [r[0] if isinstance(r, (tuple, list)) else r.get("procurement_id") or r.get("p_id") for r in (rows or [])]
    filtered_set = set(int(x) for x in filtered)
    return [pid for pid in procurement_ids if pid in filtered_set]

filters = ["ALL", "UNREVIEWED", "REVIEWED", "IN_CATEGORY", "OUT_OF_CATEGORY", "COMMERCIAL", "NON_COMMERCIAL", "UNCERTAIN", "LEGACY_NOT_INTERESTING"]
counts = count_annotation_states_sql(workset_ids, crm_db)
print("SQL COUNTS:", counts)
for f in filters:
    f_ids = filter_workset_ids_sql(workset_ids, f, crm_db)
    print(f"Filter '{f}': len(f_ids)={len(f_ids)}, expected count={counts.get(f)}")
    assert len(f_ids) == counts.get(f, 0), f"Mismatch for filter {f}: {len(f_ids)} vs {counts.get(f)}"

print("ALL FILTERS FILTER_WORKSET_IDS_SQL MATCH SQL COUNTS 100%!")
PYEOF
