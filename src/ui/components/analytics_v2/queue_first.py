"""Queue-first first screen: real S13_V4 commercial queue, bounded and fast.

No KPIs / charts / global category hierarchy on the first render - those live
in the lazy "Статистика / аналитика" section.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

POLICY = "BUSINESS_RESEARCH_ADMISSION_V2"
PAGE_SIZE = 25

_SQL = """
SELECT
    q.id                AS queue_id,
    q.procurement_id    AS procurement_id,
    q.contract_number   AS contract_number,
    q.status            AS queue_status,
    q.queue_lane        AS queue_lane,
    q.research_prior_band            AS band,
    q.research_prior_effective_score AS eff_score,
    q.priority_score    AS priority_score
FROM document_processing_queue q
WHERE q.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
  AND q.status IN ('PENDING', 'PRE_RESEARCH_WAITING', 'PROCESSING')
  ORDER BY
    CASE q.queue_lane
        WHEN 'crm_active_hot' THEN 1 WHEN 'open_active' THEN 2
        WHEN 'awarded_recent' THEN 3 WHEN 'historical_awarded' THEN 4 ELSE 5 END ASC,
    CASE q.research_prior_band
        WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3
        WHEN 'BRONZE' THEN 2 WHEN 'WOOD' THEN 1 ELSE 0 END DESC,
    COALESCE(q.research_prior_effective_score, q.priority_score) DESC NULLS LAST,
    q.id DESC
LIMIT %(limit)s
"""

_CRM_SQL = """
SELECT
    a.procurement_id AS procurement_id,
    a.admission_state AS admission_state,
    a.admission_policy_version AS policy,
    a.source_lifecycle AS lifecycle,
    a.procurement_scope_type AS scope,
    p.auction_name AS title,
    p.initial_price AS price,
    p.end_date AS end_date,
    p.delivery_end_date AS delivery_end_date,
    p.customer AS customer,
    p.delivery_region AS region,
    opp.cats AS categories,
    opp.eff_medal AS eff_medal,
    opp.eff_score AS current_effective_score
FROM crm_procurement_scope_authority a
JOIN crm_procurements p ON p.id = a.procurement_id
LEFT JOIN LATERAL (
    SELECT
        string_agg(DISTINCT o.commercial_category_code, ', ') AS cats,
        (array_agg(o.current_effective_medal ORDER BY
            CASE o.current_effective_medal
                WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3
                WHEN 'BRONZE' THEN 2 WHEN 'WOOD' THEN 1 ELSE 0 END DESC,
            o.current_effective_score DESC NULLS LAST))[1] AS eff_medal,
        max(o.current_effective_score) AS eff_score
    FROM crm_procurement_category_opportunities o
    WHERE o.procurement_id = a.procurement_id AND o.status = 'CURRENT'
) opp ON TRUE
WHERE a.procurement_id = ANY(%(ids)s)
  {flt}
"""


def _doc_db():
    import os

    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kw = require_crm_db_connect_kwargs()
    kw["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    return kw


def load_queue_page(
    *,
    limit: int = PAGE_SIZE,
    medal: Optional[str] = None,
    lifecycle: Optional[str] = None,
    scope: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Two bounded queries: V4 queue head (doc DB) + CRM join (crm DB).

    The admission gate is applied on the CRM side; only the queue *head* is
    read (no full workset, no id list over the whole table).
    """
    import psycopg2
    import psycopg2.extras

    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    flt = ""
    crm_params: Dict[str, Any] = {}
    if medal:
        flt += " AND opp.eff_medal = %(medal)s"
        crm_params["medal"] = medal
    if lifecycle:
        flt += " AND a.source_lifecycle = %(lifecycle)s"
        crm_params["lifecycle"] = lifecycle
    if scope:
        flt += " AND a.procurement_scope_type = %(scope)s"
        crm_params["scope"] = scope
    if category:
        flt += " AND opp.cats ILIKE %(cat)s"
        crm_params["cat"] = f"%{category}%"

    # 1) bounded queue head (doc DB)
    head_limit = max(int(limit) * 12, 300)
    conn = psycopg2.connect(**_doc_db())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_SQL.format(flt=""), {"limit": head_limit})
            head = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    if not head:
        return []
    ids = sorted({int(r["procurement_id"]) for r in head if r.get("procurement_id") is not None})

    # 2) CRM join + admission gate for those ids only
    crm = psycopg2.connect(**require_crm_db_connect_kwargs())
    try:
        with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_CRM_SQL.format(flt=flt), {"ids": ids, **crm_params})
            gate = {}
            for r in cur.fetchall():
                d = dict(r)
                if (
                    d.get("admission_state") == "ELIGIBLE"
                    and d.get("policy") == POLICY
                ):
                    gate[int(d["procurement_id"])] = d
    finally:
        crm.close()

    out = []
    for r in head:
        g = gate.get(int(r.get("procurement_id") or 0))
        if not g:
            continue
        out.append({**r, **g})
        if len(out) >= int(limit):
            break
    return out


def _band_badge(band: Optional[str]) -> str:
    return {"GOLD": "🥇 GOLD", "SILVER": "🥈 SILVER", "BRONZE": "🥉 BRONZE",
            "WOOD": "🪵 WOOD"}.get((band or "").upper(), "- no band")


def render_queue_first() -> None:
    """First screen: real V4 queue, 25 rows, lazy detail."""
    st.markdown("### Очередь возможностей")
    st.caption("Реальная S13_V4 коммерческая очередь · admission=BUSINESS_RESEARCH_ADMISSION_V2")

    f1, f2, f3, f4 = st.columns(4)
    medal = f1.selectbox("Медаль", ["", "GOLD", "SILVER", "BRONZE", "WOOD"], key="qf_medal")
    lifecycle = f2.selectbox(
        "Lifecycle", ["", "OPEN", "AWARDED", "WAITING_SOURCE_OUTCOME"], key="qf_lc"
    )
    scope = f3.selectbox(
        "Scope",
        ["", "DIRECT_GOODS", "WORKS_WITH_EMBEDDED_PRODUCTS", "DESIGN_PROJECT"],
        key="qf_scope",
    )
    category = f4.text_input("Категория (подстрока)", key="qf_cat")

    rows = load_queue_page(
        medal=medal or None, lifecycle=lifecycle or None,
        scope=scope or None, category=category or None,
    )
    st.caption(f"Показано {len(rows)} строк очереди (лимит {PAGE_SIZE})")
    if not rows:
        st.info("Очередь пуста по текущим фильтрам.")
        return

    for r in rows:
        medal_txt = r.get("eff_medal") or "-"
        title = (r.get("title") or "(без названия)")[:90]
        header = (
            f"{_band_badge(r.get('band'))} · {medal_txt} · {r.get('lifecycle')} / "
            f"{r.get('scope')} · {r.get('contract_number')} · {r.get('queue_status')}"
        )
        with st.expander(f"{header} — {title}", expanded=False):
            st.write(f"**contract_number:** {r.get('contract_number')}")
            st.write(f"**procurement_id:** {r.get('procurement_id')} · queue_id {r.get('queue_id')}")
            st.write(f"**lifecycle / scope:** {r.get('lifecycle')} / {r.get('scope')}")
            st.write(f"**medal / score:** {medal_txt} / {r.get('current_effective_score')}")
            st.write(f"**band / priority:** {r.get('band')} / "
                     f"{r.get('eff_score') or r.get('priority_score')}")
            st.write(f"**категории:** {r.get('categories') or '-'}")
            st.write(f"**цена:** {r.get('price')} · **регион:** {r.get('region')}")
            st.write(f"**заказчик:** {r.get('customer')}")
            st.write(f"**end / delivery_end:** {r.get('end_date')} / {r.get('delivery_end_date')}")
            st.write(f"**queue lane / status:** {r.get('queue_lane')} / {r.get('queue_status')}")
