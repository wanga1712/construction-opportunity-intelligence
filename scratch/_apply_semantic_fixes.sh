#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== APPLYING SEMANTIC RECOVERY FIXES ==="

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys

# 1. Update src/services/annotation_category_gate.py
path_acg = "/opt/CRM_Streamlit_rescue/src/services/annotation_category_gate.py"
with open(path_acg, "r", encoding="utf-8") as f:
    code_acg = f.read()

target_cso = """def category_scope_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = payload.get(CATEGORY_SCOPE_FIELD)
    return value if value in CATEGORY_SCOPE_VALUES else None"""

replacement_cso = """def category_scope_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = payload.get(CATEGORY_SCOPE_FIELD)
    if isinstance(value, dict):
        value = value.get("verdict")
    return value if value in CATEGORY_SCOPE_VALUES else None"""

assert target_cso in code_acg, "target_cso not found in annotation_category_gate.py"
code_acg = code_acg.replace(target_cso, replacement_cso)
with open(path_acg, "w", encoding="utf-8") as f:
    f.write(code_acg)
print("Updated annotation_category_gate.py")

# 2. Update src/ui/components/analytics_v2/stage_workspace.py
path_sw = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/stage_workspace.py"
with open(path_sw, "r", encoding="utf-8") as f:
    code_sw = f.read()

target_filters = """FILTERS = (
    ("ALL", "Все"),
    (UNREVIEWED, "Не проверено"),
    (REVIEWED, "Проверено"),
    (IN_CATEGORY, "В категории"),
    (OUT_OF_CATEGORY, "Вне категорий"),
    (COMMERCIAL, "Коммерчески подходит"),
    (NON_COMMERCIAL, "Коммерчески не подходит"),
    (UNCERTAIN, "Не уверен"),
    (LEGACY_NOT_INTERESTING, "Старые «Неинтересные»"),
)"""

replacement_filters = """FILTERS = (
    ("ALL", "Все"),
    (UNREVIEWED, "Не проверено"),
    (REVIEWED, "Проверено"),
    (IN_CATEGORY, "В категории"),
    (OUT_OF_CATEGORY, "Вне товарных категорий"),
    (COMMERCIAL, "Коммерчески подходит"),
    (NON_COMMERCIAL, "Коммерчески не подходит"),
    (UNCERTAIN, "Не уверен"),
    (LEGACY_NOT_INTERESTING, "Старые «Неинтересные»"),
)"""

if target_filters in code_sw:
    code_sw = code_sw.replace(target_filters, replacement_filters)
    with open(path_sw, "w", encoding="utf-8") as f:
        f.write(code_sw)
    print("Updated stage_workspace.py FILTERS")
else:
    print("FILTERS target check in stage_workspace.py:", "Вне товарных категорий" in code_sw)

# 3. Update src/services/annotation_state_service.py
path_ass = "/opt/CRM_Streamlit_rescue/src/services/annotation_state_service.py"
with open(path_ass, "r", encoding="utf-8") as f:
    code_ass = f.read()

target_lcas_loop = """        staged = is_staged_complete(payload)
        partial = is_partially_reviewed(payload)
        states[pid] = {
            "has_annotation": True,
            "annotation_id": row.get("id"),
            "annotation_version": row.get("annotation_version"),
            "created_at": row.get("created_at"),
            "annotation_state": outcome,
            "is_reviewed": staged,
            "is_category_reviewed": bool(scope),
            "is_staged_complete": staged,
            "is_partial": partial,"""

replacement_lcas_loop = """        staged = is_staged_complete(payload)
        partial = is_partially_reviewed(payload)
        is_rev = bool(scope or legacy)
        states[pid] = {
            "has_annotation": True,
            "annotation_id": row.get("id"),
            "annotation_version": row.get("annotation_version"),
            "created_at": row.get("created_at"),
            "annotation_state": outcome,
            "is_reviewed": is_rev,
            "is_category_reviewed": bool(scope),
            "is_staged_complete": staged,
            "is_partial": partial,"""

if target_lcas_loop in code_ass:
    code_ass = code_ass.replace(target_lcas_loop, replacement_lcas_loop)

target_counts_func = """def annotation_state_counts(states: dict[int, dict]) -> dict[str, int]:
    \"\"\"Staged progress counters including commercial secondary filters.\"\"\"
    total = len(states)
    reviewed = sum(1 for value in states.values() if value.get("is_staged_complete"))"""

replacement_counts_func = """def annotation_state_counts(states: dict[int, dict]) -> dict[str, int]:
    \"\"\"Staged progress counters including commercial secondary filters.\"\"\"
    total = len(states)
    reviewed = sum(1 for value in states.values() if value.get("is_reviewed"))"""

if target_counts_func in code_ass:
    code_ass = code_ass.replace(target_counts_func, replacement_counts_func)

target_sql_counts = """def count_annotation_states_sql(procurement_ids: list[int], crm_db: Any) -> dict[str, int]:
    \"\"\"Compute review filter counts via SQL ??? no full Python load needed.

    Returns the same keys as annotation_state_counts() but uses SQL aggregation.
    \"\"\"
    ids = list(dict.fromkeys(int(v) for v in procurement_ids))
    total = len(ids)
    if not ids:
        return {"ALL": 0, UNREVIEWED: 0, REVIEWED: 0, OUT_OF_CATEGORY: 0,
                IN_CATEGORY: 0, UNCERTAIN: 0, COMMERCIAL: 0, NON_COMMERCIAL: 0,
                LEGACY_NOT_INTERESTING: 0, NOT_INTERESTING: 0, PROFILED: 0,
                UNANNOTATED: 0, ANNOTATED: 0}

    rows = crm_db.execute_query(
        \"\"\"SELECT
              payload ->> 'expert_category_scope' AS scope,
              payload ->> 'expert_commercial_entry' AS commercial,
              CASE WHEN payload ->> 'expert_category_scope' IS NOT NULL
                        AND payload ->> 'expert_category_scope' != ''
                   THEN TRUE ELSE FALSE END AS has_scope,
              count(*) AS cnt
           FROM crm_v3_expert_annotations
           WHERE is_current = TRUE AND procurement_id = ANY(%s)
           GROUP BY scope, commercial, has_scope\"\"\",
        (ids,),
    )
    # Accumulate
    annotated_ids = 0
    out_cat = 0; in_cat = 0; uncertain = 0
    commercial = 0; non_commercial = 0
    reviewed = 0; legacy = 0
    for r in (rows or []):
        cnt = int(r["cnt"])
        annotated_ids += cnt
        scope = r.get("scope") or ""
        comm = r.get("commercial") or ""
        if scope == OUT_OF_CATEGORY:
            out_cat += cnt
            reviewed += cnt  # OUT is considered reviewed
        elif scope == IN_CATEGORY:
            in_cat += cnt
            reviewed += cnt
        elif scope == UNCERTAIN:
            uncertain += cnt
            reviewed += cnt
        # legacy negative: scope empty but has annotation -> count as legacy
        if not scope and cnt:
            legacy += cnt
        if comm == COMMERCIAL:
            commercial += cnt
        elif comm == NON_COMMERCIAL:
            non_commercial += cnt
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
        UNANNOTATED: total - annotated_ids,
        ANNOTATED: annotated_ids,
    }"""

replacement_sql_counts = """def count_annotation_states_sql(procurement_ids: list[int], crm_db: Any) -> dict[str, int]:
    \"\"\"Compute review filter counts via SQL aggregation — no full Python load needed.

    Returns exact same keys as annotation_state_counts().
    \"\"\"
    ids = list(dict.fromkeys(int(v) for v in procurement_ids))
    total = len(ids)
    if not ids:
        return {"ALL": 0, UNREVIEWED: 0, REVIEWED: 0, OUT_OF_CATEGORY: 0,
                IN_CATEGORY: 0, UNCERTAIN: 0, COMMERCIAL: 0, NON_COMMERCIAL: 0,
                LEGACY_NOT_INTERESTING: 0, NOT_INTERESTING: 0, PROFILED: 0,
                UNANNOTATED: 0, ANNOTATED: 0}

    rows = crm_db.execute_query(
        \"\"\"SELECT
              CASE 
                WHEN jsonb_typeof(payload -> 'expert_category_scope') = 'object' 
                THEN payload -> 'expert_category_scope' ->> 'verdict' 
                ELSE payload ->> 'expert_category_scope' 
              END AS scope,
              payload ->> 'expert_commercial_entry' AS commercial,
              payload ->> 'expert_commercial_verdict' AS comm_verdict,
              payload ->> 'expert_scope_verdict' AS scope_verdict,
              payload ->> 'expert_medal' AS medal,
              payload -> 'error_reasons' AS error_reasons,
              count(*) AS cnt
           FROM crm_v3_expert_annotations
           WHERE is_current = TRUE AND procurement_id = ANY(%s)
           GROUP BY scope, commercial, comm_verdict, scope_verdict, medal, error_reasons\"\"\",
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
    }"""

if target_sql_counts in code_ass:
    code_ass = code_ass.replace(target_sql_counts, replacement_sql_counts)

# Add filter_workset_ids_sql to annotation_state_service.py
filter_workset_ids_func = """

def filter_workset_ids_sql(procurement_ids: list[int], selected_review: str, crm_db: Any) -> list[int]:
    \"\"\"Filter procurement_ids by selected review state in SQL before pagination.\"\"\"
    if not procurement_ids or selected_review == "ALL":
        return procurement_ids
    scope_expr = "CASE WHEN jsonb_typeof(payload -> 'expert_category_scope') = 'object' THEN payload -> 'expert_category_scope' ->> 'verdict' ELSE payload ->> 'expert_category_scope' END"
    if selected_review == UNREVIEWED:
        sql = f\"\"\"
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
        \"\"\"
        rows = crm_db.execute_query(sql, (procurement_ids, procurement_ids))
    elif selected_review == REVIEWED:
        sql = f\"\"\"
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
        \"\"\"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == OUT_OF_CATEGORY:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'OUT_OF_CATEGORY'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == IN_CATEGORY:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'IN_CATEGORY'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == UNCERTAIN:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND {scope_expr} = 'UNCERTAIN'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == COMMERCIAL:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND ea.payload ->> 'expert_commercial_entry' = 'COMMERCIAL'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == NON_COMMERCIAL:
        sql = f"SELECT ea.procurement_id FROM crm_v3_expert_annotations ea WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) AND ea.payload ->> 'expert_commercial_entry' = 'NON_COMMERCIAL'"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    elif selected_review == LEGACY_NOT_INTERESTING:
        sql = f\"\"\"
            SELECT ea.procurement_id FROM crm_v3_expert_annotations ea 
            WHERE ea.is_current = TRUE AND ea.procurement_id = ANY(%s) 
              AND ({scope_expr} IS NULL OR {scope_expr} = '')
              AND (
                ea.payload ->> 'expert_commercial_verdict' = 'NO_COMMERCIAL_ENTRY'
                OR ea.payload ->> 'expert_scope_verdict' = 'OUT_OF_PROFILE'
                OR ea.payload ->> 'expert_medal' = 'NCE'
              )
        \"\"\"
        rows = crm_db.execute_query(sql, (procurement_ids,))
    else:
        rows = []
    filtered = [r[0] if isinstance(r, (tuple, list)) else r.get("procurement_id") or r.get("p_id") for r in (rows or [])]
    filtered_set = set(int(x) for x in filtered)
    return [pid for pid in procurement_ids if pid in filtered_set]
"""

if "def filter_workset_ids_sql" not in code_ass:
    code_ass += filter_workset_ids_func

with open(path_ass, "w", encoding="utf-8") as f:
    f.write(code_ass)
print("Updated annotation_state_service.py")

# 4. Update src/ui/components/analytics_v2/tabs.py
path_tabs = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(path_tabs, "r", encoding="utf-8") as f:
    code_tabs = f.read()

target_render_review = """def _render_review_filter_from_counts(
    counts: dict[str, int], session_key: str, *, on_change=None
) -> str:
    \"\"\"Render review filter pills using pre-computed SQL counts.\"\"\"
    from src.ui.components.analytics_v2.stage_workspace import FILTERS
    labels = [f"{label} ?? {counts.get(key, 0)}" for key, label in FILTERS]
    selected_label = st.pills(
        "??????????????",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]"""

replacement_render_review = """def _render_review_filter_from_counts(
    counts: dict[str, int], session_key: str, *, on_change=None
) -> str:
    \"\"\"Render review filter pills using pre-computed SQL counts.\"\"\"
    from src.ui.components.analytics_v2.stage_workspace import FILTERS
    labels = [f"{label} · {counts.get(key, 0)}" for key, label in FILTERS]
    selected_label = st.pills(
        "Экспертная разметка",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]"""

if target_render_review in code_tabs:
    code_tabs = code_tabs.replace(target_render_review, replacement_render_review)
else:
    print("WARNING: target_render_review not found exactly in tabs.py")

target_torgi_workset = """    sql_counts = count_annotation_states_sql(workset_ids, crm_db)
    selected_review = _render_review_filter_from_counts(
        sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    # ── Filtered count for pagination ──
    filtered_total = sql_counts.get(selected_review, sql_counts["ALL"])
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, workset_ids)"""

replacement_torgi_workset = """    from src.services.annotation_state_service import filter_workset_ids_sql
    sql_counts = count_annotation_states_sql(workset_ids, crm_db)
    selected_review = _render_review_filter_from_counts(
        sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    # ── SQL filter before pagination ──
    filtered_workset_ids = filter_workset_ids_sql(workset_ids, selected_review, crm_db)
    filtered_total = len(filtered_workset_ids)
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, filtered_workset_ids)"""

if target_torgi_workset in code_tabs:
    code_tabs = code_tabs.replace(target_torgi_workset, replacement_torgi_workset)
else:
    print("WARNING: target_torgi_workset not found exactly in tabs.py")

with open(path_tabs, "w", encoding="utf-8") as f:
    f.write(code_tabs)
print("Updated tabs.py")

PYEOF
