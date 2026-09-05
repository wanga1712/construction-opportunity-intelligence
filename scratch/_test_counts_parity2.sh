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
from src.services.annotation_category_gate import category_scope_of, is_legacy_negative_payload
from src.services.expert_commercial_entry import commercial_entry_of
from src.services.annotation_state_service import (
    UNANNOTATED, ANNOTATED, NOT_INTERESTING, UNREVIEWED, REVIEWED, PROFILED,
    OUT_OF_CATEGORY, IN_CATEGORY, UNCERTAIN, LEGACY_NOT_INTERESTING,
    COMMERCIAL, NON_COMMERCIAL
)

_, _, crm_db, _ = connect_databases()

# Update category_scope_of in runtime to test dict handling
import src.services.annotation_category_gate as acg
_orig_cso = acg.category_scope_of
def category_scope_of_fixed(payload: dict | None) -> str | None:
    if not payload:
        return None
    val = payload.get("expert_category_scope")
    if isinstance(val, dict):
        val = val.get("verdict")
    return val if val in acg.CATEGORY_SCOPE_VALUES else None
acg.category_scope_of = category_scope_of_fixed

import src.services.annotation_state_service as ass
ass.category_scope_of = category_scope_of_fixed

def count_annotation_states_sql_fixed(procurement_ids: list[int], crm_db) -> dict[str, int]:
    ids = list(dict.fromkeys(int(v) for v in procurement_ids))
    total = len(ids)
    if not ids:
        return {
            "ALL": 0, UNREVIEWED: 0, REVIEWED: 0, OUT_OF_CATEGORY: 0,
            IN_CATEGORY: 0, UNCERTAIN: 0, COMMERCIAL: 0, NON_COMMERCIAL: 0,
            LEGACY_NOT_INTERESTING: 0, NOT_INTERESTING: 0, PROFILED: 0,
            UNANNOTATED: 0, ANNOTATED: 0
        }

    rows = crm_db.execute_query(
        """SELECT
              COALESCE(
                payload ->> 'expert_category_scope',
                payload -> 'expert_category_scope' ->> 'verdict'
              ) AS scope,
              payload ->> 'expert_commercial_entry' AS commercial,
              payload ->> 'expert_commercial_verdict' AS comm_verdict,
              payload ->> 'expert_scope_verdict' AS scope_verdict,
              payload ->> 'expert_medal' AS medal,
              payload -> 'error_reasons' AS error_reasons,
              count(*) AS cnt
           FROM crm_v3_expert_annotations
           WHERE is_current = TRUE AND procurement_id = ANY(%s)
           GROUP BY scope, commercial, comm_verdict, scope_verdict, medal, error_reasons""",
        (ids,),
    )
    annotated_cnt = 0
    out_cat = 0; in_cat = 0; uncertain = 0
    commercial = 0; non_commercial = 0
    legacy = 0
    for r in (rows or []):
        cnt = int(r["cnt"])
        annotated_cnt += cnt
        scope = r.get("scope") or ""
        comm = r.get("commercial") or ""
        
        reasons = r.get("error_reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        is_legacy = (not scope) and (
            r.get("comm_verdict") == "NO_COMMERCIAL_ENTRY"
            or r.get("scope_verdict") == "OUT_OF_PROFILE"
            or r.get("medal") == "NCE"
            or "OUT_OF_PROFILE" in reasons
        )
        
        if scope == OUT_OF_CATEGORY:
            out_cat += cnt
        elif scope == IN_CATEGORY:
            in_cat += cnt
        elif scope == UNCERTAIN:
            uncertain += cnt
            
        if is_legacy:
            legacy += cnt

        if comm == COMMERCIAL:
            commercial += cnt
        elif comm == NON_COMMERCIAL:
            non_commercial += cnt

    reviewed = in_cat + out_cat + uncertain + legacy
    not_interesting = legacy + out_cat
    return {
        "ALL": total,
        UNREVIEWED: total - reviewed,
        REVIEWED: reviewed,
        OUT_OF_CATEGORY: out_cat,
        IN_CATEGORY: in_cat,
        UNCERTAIN: uncertain,
        COMMERCIAL: commercial,
        NON_COMMERCIAL: non_commercial,
        LEGACY_NOT_INTERESTING: legacy,
        NOT_INTERESTING: not_interesting,
        PROFILED: max(0, reviewed - out_cat),
        UNANNOTATED: total - annotated_cnt,
        ANNOTATED: annotated_cnt,
    }

# Test on all 20 annotations
rows = crm_db.execute_query("SELECT procurement_id FROM crm_v3_expert_annotations WHERE is_current = TRUE")
all_pids = [r["procurement_id"] for r in rows]

py_states = ass.load_current_annotation_states(all_pids, crm_db)
py_counts = ass.annotation_state_counts(py_states)
sql_counts = count_annotation_states_sql_fixed(all_pids, crm_db)

print("=== PARITY TEST ON ALL 20 DB ANNOTATIONS ===")
print("PY COUNTS: ", py_counts)
print("SQL COUNTS:", sql_counts)
print("PARITY MATCH:", py_counts == sql_counts)
assert py_counts == sql_counts, f"Mismatch: {py_counts} vs {sql_counts}"

# Test on 5152 workset IDs
from src.ui.components.analytics_v2.tabs import _stage_workset_ids
workset_ids = _stage_workset_ids("torgi")

py_ws_states = ass.load_current_annotation_states(workset_ids, crm_db)
py_ws_counts = ass.annotation_state_counts(py_ws_states)
sql_ws_counts = count_annotation_states_sql_fixed(workset_ids, crm_db)

print("\n=== PARITY TEST ON 5152 TORGI WORKSET IDs ===")
print("PY WS COUNTS: ", py_ws_counts)
print("SQL WS COUNTS:", sql_ws_counts)
print("PARITY MATCH:", py_ws_counts == sql_ws_counts)
assert py_ws_counts == sql_ws_counts, f"Mismatch: {py_ws_counts} vs {sql_ws_counts}"

print("\nPERFECT 100% PARITY ACHIEVED!")
PYEOF
