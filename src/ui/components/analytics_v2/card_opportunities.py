"""Batch-load and render category opportunity blocks for procurement cards.

Provides:
- batch_load_opportunities(): one query for page of procurement IDs
- batch_load_evidence_preview(): top evidence per opportunity (lazy, match_details)
- render_card_opportunities(): compact blocks on collapsed card
- REASON_LABELS: human-facing reason map for effective_reason codes

Hard invariants:
- CATEGORY_OPPORTUNITY_IS_MEDAL_UNIT=YES — each category renders independently
- EFFECTIVE_MEDAL_IS_NOT_DOCUMENT_VERIFIED=YES — never label medal as verified by documents
- Empty category → do not render placeholder
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

# ── Human-facing reason labels ────────────────────────────────────────────

REASON_LABELS: Dict[str, str] = {
    "ACTIVE_TIMING_DECAY": "Снижено из-за приближения/изменения срока",
    "POST_AWARD_TIMING_DECAY": "Снижено после завершения торгов",
    "MIGRATION_SNAPSHOT_NOT_INITIAL": "Перенесено из прежней версии",
    "FIRST_ACCEPTANCE": "Первоначальная оценка",
}

_MEDAL_EMOJI = {
    "GOLD": "🥇",
    "SILVER": "🥈",
    "BRONZE": "🥉",
    "WOOD": "🪵",
}

_MEDAL_CSS_COLOR = {
    "GOLD": "#B8860B",
    "SILVER": "#708090",
    "BRONZE": "#8B4513",
    "WOOD": "#6B4E3D",
}


# ── Batch data loading (no N+1) ──────────────────────────────────────────

def batch_load_opportunities(
    procurement_ids: List[int],
    crm_db: Any,
) -> Dict[int, List[dict]]:
    """Load category opportunities for a batch of procurement IDs.

    Returns {procurement_id: [opp_dict, ...]} with status='CURRENT' only.
    Single SQL query for the entire page.
    """
    if not procurement_ids:
        return {}

    sql = """
        SELECT
            id,
            procurement_id,
            category_code,
            subcategory_code,
            candidate_initial_medal,
            current_effective_medal,
            current_effective_reason,
            initial_medal_provenance,
            status
        FROM crm_procurement_category_opportunities
        WHERE procurement_id = ANY(%(ids)s)
          AND status = 'CURRENT'
        ORDER BY procurement_id, id
    """
    rows = crm_db.execute_query(sql, {"ids": procurement_ids})

    result: Dict[int, List[dict]] = {}
    for row in rows:
        pid = row["procurement_id"]
        result.setdefault(pid, []).append(dict(row))
    return result


def batch_load_evidence_preview(
    procurement_ids: List[int],
    doc_db_connect: Any,
) -> Dict[str, dict]:
    """Load top-1 evidence per (procurement_id, category_code).

    Uses document_match_details from document_intelligence DB.
    Returns {f"{pid}:{cat}": {matched_term, page_or_sheet, document_name}} keyed
    by procurement_id:category_code string.

    Single query for all procurement IDs — no N+1.
    """
    if not procurement_ids:
        return {}

    sql = """
        SELECT DISTINCT ON (dmd.procurement_id, dmd.category_code)
            dmd.procurement_id,
            dmd.category_code,
            dmd.matched_term,
            dmd.page_or_sheet,
            dm.document_name
        FROM document_match_details dmd
        JOIN document_matches dm ON dm.id = dmd.match_id
        WHERE dmd.procurement_id = ANY(%(ids)s)
        ORDER BY dmd.procurement_id, dmd.category_code,
                 dmd.score DESC NULLS LAST, dmd.id
    """
    try:
        conn = doc_db_connect()
        try:
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, {"ids": procurement_ids})
                rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return {}

    result: Dict[str, dict] = {}
    for row in rows:
        key = f"{row['procurement_id']}:{row['category_code']}"
        result[key] = dict(row)
    return result


def batch_load_structured_entities(
    procurement_ids: List[int],
    doc_db_connect: Any,
) -> Dict[str, List[dict]]:
    """Load trusted structured entities per (procurement_id, category_code).

    Returns {f"{pid}:{cat}": [entity_dict, ...]} — preferred over match_details
    when available (richer data: product_name, quantity, price).
    """
    if not procurement_ids:
        return {}

    sql = """
        SELECT
            se.procurement_id,
            se.category_code,
            se.subcategory_code,
            se.product_name_normalized,
            se.product_name_raw,
            se.quantity_value,
            se.quantity_unit_normalized,
            se.quantity_unit_raw,
            se.unit_price_value,
            se.total_price_value,
            dm.document_name,
            dmd.page_or_sheet
        FROM structured_entities se
        JOIN structured_extraction_runs ser ON ser.id = se.run_id
        JOIN document_match_details dmd ON dmd.id = se.detail_id
        JOIN document_matches dm ON dm.id = dmd.match_id
        WHERE se.procurement_id = ANY(%(ids)s)
        ORDER BY se.procurement_id, se.category_code, se.id
    """
    try:
        conn = doc_db_connect()
        try:
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, {"ids": procurement_ids})
                rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return {}

    result: Dict[str, List[dict]] = {}
    for row in rows:
        key = f"{row['procurement_id']}:{row['category_code']}"
        result.setdefault(key, []).append(dict(row))
    return result


# ── Card rendering ────────────────────────────────────────────────────────

def render_card_opportunities(
    procurement_id: int,
    opps: List[dict],
    evidence: Dict[str, dict],
    entities: Dict[str, List[dict]],
) -> None:
    """Render category opportunity blocks for a single card.

    Called from stage_workspace._summary() for each card in the list.
    Renders nothing if opps is empty.
    """
    if not opps:
        return

    for opp in opps:
        cat = opp.get("category_code") or ""
        subcat = opp.get("subcategory_code") or ""
        initial = opp.get("candidate_initial_medal")
        current = opp.get("current_effective_medal")
        reason_code = opp.get("current_effective_reason") or ""

        if not cat:
            continue

        # Category name (uppercased for visibility)
        cat_display = cat.replace("_", " ").upper()
        subcat_display = subcat.replace("_", " ").capitalize() if subcat else ""

        # Medal transition
        medal_html = _medal_transition_html(initial, current)

        # Human reason
        reason_parts = [REASON_LABELS.get(r.strip(), r.strip())
                        for r in reason_code.split("|") if r.strip()]
        reason_text = "; ".join(reason_parts) if reason_parts else ""

        # Build block HTML
        lines = [f"<div style='margin:0.4rem 0 0.15rem;padding:0.35rem 0.5rem;"
                 f"border-left:3px solid {_MEDAL_CSS_COLOR.get(current, '#999')};'>"]
        lines.append(f"<b>{cat_display}</b>")
        if subcat_display:
            lines.append(f"<br><span style='color:#666;font-size:0.85em'>{subcat_display}</span>")
        lines.append(f"<br>{medal_html}")
        if reason_text and reason_code != "FIRST_ACCEPTANCE":
            lines.append(f"<br><span style='color:#888;font-size:0.82em'>{reason_text}</span>")

        # Evidence preview — prefer structured entities, fall back to match_details
        key = f"{procurement_id}:{cat}"
        ent_list = entities.get(key, [])
        ev = evidence.get(key)

        if ent_list:
            ent = ent_list[0]
            name = ent.get("product_name_normalized") or ent.get("product_name_raw") or ""
            qty = ent.get("quantity_value")
            unit = ent.get("quantity_unit_normalized") or ent.get("quantity_unit_raw") or ""
            doc = ent.get("document_name") or ""
            page = ent.get("page_or_sheet") or ""
            finding = name
            if qty is not None:
                finding += f" · {qty} {unit}".rstrip()
            if finding:
                lines.append(f"<br><span style='font-size:0.85em'>{finding}</span>")
            if doc:
                loc = f" · {page}" if page else ""
                lines.append(f"<br><span style='color:#2e7d32;font-size:0.82em'>"
                             f"✓ {doc}{loc}</span>")
        elif ev:
            term = ev.get("matched_term") or ""
            doc = ev.get("document_name") or ""
            page = ev.get("page_or_sheet") or ""
            if term:
                lines.append(f"<br><span style='font-size:0.85em'>{term}</span>")
            if doc:
                loc = f" · {page}" if page else ""
                lines.append(f"<br><span style='color:#2e7d32;font-size:0.82em'>"
                             f"✓ {doc}{loc}</span>")

        lines.append("</div>")
        st.markdown("".join(lines), unsafe_allow_html=True)


def _medal_transition_html(initial: Optional[str], current: Optional[str]) -> str:
    """Format medal transition as compact HTML."""
    if not current:
        return "<span style='color:#999'>Оценка не установлена</span>"

    cur_emoji = _MEDAL_EMOJI.get(current, "")
    cur_color = _MEDAL_CSS_COLOR.get(current, "#666")

    if initial and initial != current:
        ini_emoji = _MEDAL_EMOJI.get(initial, "")
        return (f"<span style='color:#999'>{ini_emoji} {initial}</span>"
                f" → <b style='color:{cur_color}'>{cur_emoji} {current}</b>")
    return f"<b style='color:{cur_color}'>{cur_emoji} {current}</b>"
