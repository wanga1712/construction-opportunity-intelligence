#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 9: PERFORMANCE FIX ==="

echo "--- Create annotation_state_service SQL count function ---"
cat >> src/services/annotation_state_service.py << 'PYEOF'


def count_annotation_states_sql(procurement_ids: list[int], crm_db: Any) -> dict[str, int]:
    """Compute review filter counts via SQL — no full Python load needed.

    Returns the same keys as annotation_state_counts() but uses SQL aggregation.
    """
    ids = list(dict.fromkeys(int(v) for v in procurement_ids))
    total = len(ids)
    if not ids:
        return {"ALL": 0, UNREVIEWED: 0, REVIEWED: 0, OUT_OF_CATEGORY: 0,
                IN_CATEGORY: 0, UNCERTAIN: 0, COMMERCIAL: 0, NON_COMMERCIAL: 0,
                LEGACY_NOT_INTERESTING: 0, NOT_INTERESTING: 0, PROFILED: 0,
                UNANNOTATED: 0, ANNOTATED: 0}

    rows = crm_db.execute_query(
        """SELECT
              payload ->> 'expert_category_scope' AS scope,
              payload ->> 'expert_commercial_entry' AS commercial,
              CASE WHEN payload ->> 'expert_category_scope' IS NOT NULL
                        AND payload ->> 'expert_category_scope' != ''
                   THEN TRUE ELSE FALSE END AS has_scope,
              count(*) AS cnt
           FROM crm_v3_expert_annotations
           WHERE is_current = TRUE AND procurement_id = ANY(%s)
           GROUP BY scope, commercial, has_scope""",
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
    }


def annotation_filter_sql_clause(selected_state: str) -> str:
    """Return a SQL WHERE fragment that implements the review filter on the procurement IDs.

    Returns '' (empty string) for 'ALL' filter.
    Requires LEFT JOIN crm_v3_expert_annotations ea
        ON ea.procurement_id = cp.id AND ea.is_current = TRUE
    """
    if selected_state == "ALL":
        return ""
    if selected_state == REVIEWED:
        return "AND ea.id IS NOT NULL AND ea.payload ->> 'expert_category_scope' IS NOT NULL AND ea.payload ->> 'expert_category_scope' != ''"
    if selected_state == UNREVIEWED:
        return "AND (ea.id IS NULL OR ea.payload ->> 'expert_category_scope' IS NULL OR ea.payload ->> 'expert_category_scope' = '')"
    if selected_state == OUT_OF_CATEGORY:
        return "AND ea.payload ->> 'expert_category_scope' = 'OUT_OF_CATEGORY'"
    if selected_state == IN_CATEGORY:
        return "AND ea.payload ->> 'expert_category_scope' = 'IN_CATEGORY'"
    if selected_state == UNCERTAIN:
        return "AND ea.payload ->> 'expert_category_scope' = 'UNCERTAIN'"
    if selected_state == COMMERCIAL:
        return "AND ea.payload ->> 'expert_commercial_entry' = 'COMMERCIAL'"
    if selected_state == NON_COMMERCIAL:
        return "AND ea.payload ->> 'expert_commercial_entry' = 'NON_COMMERCIAL'"
    if selected_state == LEGACY_NOT_INTERESTING:
        return "AND ea.id IS NOT NULL AND (ea.payload ->> 'expert_category_scope' IS NULL OR ea.payload ->> 'expert_category_scope' = '')"
    return ""
PYEOF

echo "ANNOTATION_STATE_SQL_ADDED=YES"

echo "--- Now patch tabs.py torgi to use SQL counts + page-only annotation load ---"

# We need to modify _render_torgi_tab to:
# 1. Get workset_ids (keep - for global counts and total display)
# 2. Use SQL counts instead of full Python load for filter rendering
# 3. Push review filter into SQL for _load_torgi
# 4. Load annotation_states only for page IDs

cat > /tmp/_patch_torgi.py << 'PYEOF'
import re

filepath = "/opt/CRM_Streamlit_rescue/src/ui/components/analytics_v2/tabs.py"
with open(filepath, 'r') as f:
    content = f.read()

# Find the torgi tab section and replace the annotation loading pattern
old_pattern = """    workset_ids = _stage_workset_ids("torgi")
    sort_mode = st.radio(
        "Сортировка по сроку",
        list(DEADLINE_SORT_LABELS),
        format_func=lambda value: DEADLINE_SORT_LABELS[value],
        horizontal=True,
        key="torgi_deadline_sort",
        on_change=_reset_torgi_page,
    )
    from src.services.annotation_state_service import load_current_annotation_states
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    annotation_states = load_current_annotation_states(workset_ids, crm_db)
    selected_review = render_review_filter(
        annotation_states, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    selected_ids = filtered_review_ids(annotation_states, selected_review)
    page, offset = _page_offset("torgi", len(selected_ids))
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, selected_ids)"""

new_pattern = """    workset_ids = _stage_workset_ids("torgi")
    sort_mode = st.radio(
        "Сортировка по сроку",
        list(DEADLINE_SORT_LABELS),
        format_func=lambda value: DEADLINE_SORT_LABELS[value],
        horizontal=True,
        key="torgi_deadline_sort",
        on_change=_reset_torgi_page,
    )
    from src.services.annotation_state_service import (
        count_annotation_states_sql,
        annotation_filter_sql_clause,
        load_current_annotation_states,
    )
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    # ── SQL-level counts (no full Python load) ──
    sql_counts = count_annotation_states_sql(workset_ids, crm_db)
    selected_review = _render_review_filter_from_counts(
        sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    # ── Filtered count for pagination ──
    filtered_total = sql_counts.get(selected_review, sql_counts["ALL"])
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, workset_ids,
                        annotation_filter=annotation_filter_sql_clause(selected_review))
    # ── Page-only annotation state load ──
    page_ids = [c["id"] for c in cards]
    annotation_states = load_current_annotation_states(page_ids, crm_db)"""

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern)
    print("TORGI_PATCH_APPLIED=YES")
else:
    print("TORGI_PATCH_APPLIED=NO (exact match not found)")
    # Debug: show what's actually there
    import textwrap
    idx = content.find('workset_ids = _stage_workset_ids("torgi")')
    if idx >= 0:
        print("Found workset_ids line at position:", idx)
        print("Surrounding 800 chars:")
        print(content[idx:idx+800])
    else:
        print("workset_ids line NOT FOUND")

with open(filepath, 'w') as f:
    f.write(content)
PYEOF

/opt/CRM_Streamlit/.venv313/bin/python /tmp/_patch_torgi.py

echo "PHASE_9_TORGI_PATCH=DONE"
