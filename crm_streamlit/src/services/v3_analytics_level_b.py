"""Level B (V3 schema) enrichment for analytics snapshot — READ ONLY."""
from __future__ import annotations

from typing import Any, Dict

from src.services.v3_analytics_service import (
    VISIBLE_ACTIVE_STATES,
    V3AnalyticsSnapshot,
    _safe_query,
    _scalar,
)


def enrich_level_b(
    snap: V3AnalyticsSnapshot,
    crm_db,
    *,
    contour: str,
    category: str,
    track: str,
    medal: str,
    lifecycle: str,
) -> None:
    snap.okpd_priors_status = "LIVE"
    snap.title_signals_status = "LIVE"
    snap.versions["v3_schema_active"] = True
    snap.versions["status"] = "V3 schema active"
    snap.versions["registry_version"] = "live"
    snap.failures["V3_NOT_READY"] = 0

    where = ["1=1"]
    params: Dict[str, Any] = {}
    if category != "ALL":
        where.append("commercial_category_code = %(category)s")
        params["category"] = category
    if track != "ALL":
        where.append("opportunity_track = %(track)s")
        params["track"] = track
    if medal != "ALL":
        where.append("candidate_medal = %(medal)s")
        params["medal"] = medal
    if lifecycle != "ALL":
        where.append("commercial_state = %(lifecycle)s")
        params["lifecycle"] = lifecycle
    if contour == "44":
        where.append("source_contour = 'PUBLIC_44FZ'")
    elif contour == "223":
        where.append("source_contour = 'CORPORATE_223FZ'")
    wsql = " AND ".join(where)

    agg = _safe_query(
        crm_db,
        f"""
        SELECT
          count(*) AS total_opportunities,
          count(DISTINCT procurement_id) AS procurements_with_opportunities,
          count(DISTINCT procurement_id) FILTER (
            WHERE commercial_state = ANY(%(vis)s)
          ) AS active_leads,
          count(*) FILTER (WHERE candidate_medal = 'GOLD') AS gold,
          count(*) FILTER (WHERE candidate_medal = 'SILVER') AS silver,
          count(*) FILTER (WHERE candidate_medal = 'BRONZE') AS bronze,
          count(*) FILTER (WHERE candidate_medal = 'WOOD') AS wood,
          count(*) FILTER (WHERE commercial_state = 'REVIEW_REQUIRED') AS review_required
        FROM crm_procurement_category_opportunities
        WHERE {wsql}
        """,
        {**params, "vis": list(VISIBLE_ACTIVE_STATES)},
    )
    if agg:
        row = agg[0]
        snap.total_opportunities = int(row.get("total_opportunities") or 0)
        snap.procurements_with_opportunities = int(
            row.get("procurements_with_opportunities") or 0
        )
        snap.active_leads = int(row.get("active_leads") or 0)
        snap.candidate_gold = int(row.get("gold") or 0)
        snap.candidate_silver = int(row.get("silver") or 0)
        snap.candidate_bronze = int(row.get("bronze") or 0)
        snap.candidate_wood = int(row.get("wood") or 0)
        snap.review_required = int(row.get("review_required") or 0)

    snap.routed_procurements = snap.procurements_with_opportunities
    snap.pending_routing = max(0, snap.crm_projected - snap.routed_procurements)
    snap.failures["PENDING_ROUTING"] = snap.pending_routing

    for row in _safe_query(
        crm_db,
        f"""
        SELECT commercial_state AS st, count(*) AS c
        FROM crm_procurement_category_opportunities WHERE {wsql} GROUP BY 1
        """,
        params,
    ):
        stv = str(row.get("st") or "")
        if stv in snap.lifecycle:
            snap.lifecycle[stv] = int(row.get("c") or 0)

    for row in _safe_query(
        crm_db,
        f"""
        SELECT opportunity_track AS tr,
               count(*) AS opportunities,
               count(DISTINCT procurement_id) AS procurements,
               count(*) FILTER (WHERE candidate_medal = 'GOLD') AS gold,
               count(*) FILTER (WHERE candidate_medal = 'SILVER') AS silver,
               count(*) FILTER (WHERE candidate_medal = 'BRONZE') AS bronze,
               count(*) FILTER (WHERE candidate_medal = 'WOOD') AS wood
        FROM crm_procurement_category_opportunities
        WHERE {wsql}
        GROUP BY 1
        """,
        params,
    ):
        tr = str(row.get("tr") or "")
        if tr in snap.tracks:
            snap.tracks[tr] = {
                "procurements": int(row.get("procurements") or 0),
                "opportunities": int(row.get("opportunities") or 0),
                "GOLD": int(row.get("gold") or 0),
                "SILVER": int(row.get("silver") or 0),
                "BRONZE": int(row.get("bronze") or 0),
                "WOOD": int(row.get("wood") or 0),
            }

    snap.category_rows = _safe_query(
        crm_db,
        f"""
        SELECT commercial_category_code AS category,
               count(DISTINCT procurement_id) AS unique_procurements,
               count(*) AS total_opportunities,
               count(*) FILTER (WHERE opportunity_track = 'DIRECT_SUPPLY') AS direct_supply,
               count(*) FILTER (WHERE opportunity_track = 'EMBEDDED_MATERIAL') AS embedded_material,
               count(*) FILTER (WHERE opportunity_track = 'DESIGN_REQUIREMENT') AS design_requirement,
               count(*) FILTER (WHERE opportunity_track = 'DESIGN_INFLUENCE') AS design_influence,
               count(*) FILTER (WHERE candidate_medal = 'GOLD') AS candidate_gold,
               count(*) FILTER (WHERE candidate_medal = 'SILVER') AS candidate_silver,
               count(*) FILTER (WHERE candidate_medal = 'BRONZE') AS candidate_bronze,
               count(*) FILTER (WHERE candidate_medal = 'WOOD') AS candidate_wood
        FROM crm_procurement_category_opportunities
        WHERE {wsql}
        GROUP BY 1
        ORDER BY total_opportunities DESC, category
        """,
        params,
    )

    snap.positive_title_signals = _scalar(
        crm_db,
        "SELECT count(*) FROM crm_category_routing_signals "
        "WHERE active AND signal_type = 'POSITIVE_SIGNAL'",
    )
    snap.negative_title_signals = _scalar(
        crm_db,
        "SELECT count(*) FROM crm_category_routing_signals "
        "WHERE active AND signal_type = 'NEGATIVE_SIGNAL'",
    )
    snap.hard_exclusions = _scalar(
        crm_db,
        "SELECT count(*) FROM crm_category_routing_signals "
        "WHERE active AND signal_type = 'HARD_EXCLUSION'",
    )

    for row in _safe_query(
        crm_db,
        """
        SELECT bucket, count(*) AS c FROM (
          SELECT procurement_id,
                 CASE
                   WHEN count(*) = 1 THEN '1'
                   WHEN count(*) = 2 THEN '2'
                   WHEN count(*) = 3 THEN '3'
                   ELSE '4+'
                 END AS bucket
          FROM crm_procurement_category_opportunities
          GROUP BY procurement_id
        ) t GROUP BY 1
        """,
    ):
        b = str(row.get("bucket") or "")
        if b in snap.multi_category:
            snap.multi_category[b] = int(row.get("c") or 0)

    if snap.procurements_with_opportunities:
        snap.avg_opportunities_per_procurement = round(
            snap.total_opportunities / snap.procurements_with_opportunities, 2
        )
    snap.discovery_required = 0
    snap.level_c_ready = False
    snap.confirmed_status = "Нет данных подтверждения"
