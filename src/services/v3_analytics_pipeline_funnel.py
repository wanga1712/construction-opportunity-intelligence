"""Pipeline funnel metrics for Analytics V3 snapshot (computed on refresh only)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.services.v3_analytics_metric_state import MetricState


def _okpd_bucket(code: Optional[str]) -> str:
    c = (code or "").strip()
    if not c:
        return "MISSING_OKPD"
    if c.startswith(("41.", "42.", "43.")):
        return "CONSTRUCTION_OKPD"
    if c.startswith(("71.", "74.")):
        return "DESIGN_PIR_OKPD"
    if c.startswith("26.20") or c.startswith("26.2"):
        return "COMPUTERS_OKPD"
    if c.startswith("27.40") or c.startswith("27.4"):
        return "LIGHTING_OKPD"
    return "OTHER_OKPD"


def build_pipeline_funnel(snap) -> Dict[str, Any]:
    """Assemble labeled funnel stages from Level-A/B snapshot fields."""
    s7_open = int(snap.source_open or 0)
    s7_waiting = int(snap.source_waiting or 0)
    s7_awarded = int(snap.awarded_history_excluded or 0)  # full history stored here historically
    # Prefer explicit full-history fields if present
    s7_awarded_full = int(
        getattr(snap, "s7_awarded_full_history_total", None)
        or snap.source_44_awarded_all + snap.source_223_awarded_all
        or s7_awarded
    )
    projected_open = int(getattr(snap, "projected_open", 0) or snap.crm_torgi or 0)
    projected_waiting = int(getattr(snap, "projected_waiting", 0) or 0)
    projected_awarded = int(getattr(snap, "projected_awarded_relevant", 0) or snap.crm_razygranye or 0)
    excluded = max(0, s7_awarded_full - projected_awarded)

    has_routing = int(snap.total_opportunities or 0) > 0 or int(snap.routed_procurements or 0) > 0
    routing_state = MetricState.VALUE if (snap.level_b_ready and has_routing) else MetricState.NOT_STARTED
    docs_state = MetricState.NOT_STARTED  # pipeline off
    confirmed_state = MetricState.NOT_STARTED if not snap.level_c_ready else MetricState.VALUE

    okpd = getattr(snap, "okpd_business_funnel", None) or {
        "CONSTRUCTION_OKPD": 0,
        "DESIGN_PIR_OKPD": 0,
        "COMPUTERS_OKPD": 0,
        "LIGHTING_OKPD": 0,
        "OTHER_OKPD": 0,
        "MISSING_OKPD": int(snap.crm_okpd_null or 0),
    }

    routing = getattr(snap, "ai_routing_stages", None) or {
        "PENDING_ROUTING": int(snap.crm_projected or 0),
        "SENT_TO_MODEL": 0,
        "ROUTING_COMPLETED": 0,
        "ROUTING_FAILED": 0,
        "REVIEW_REQUIRED": 0,
        "UNKNOWN": 0,
        "model": "qwen2.5:7b",
        "legacy_ai_assessments_excluded": True,
    }

    commercial = getattr(snap, "commercial_result", None) or {
        "state": routing_state.value,
        "CATEGORY_ASSIGNED": None,
        "SUBCATEGORY_ASSIGNED": None,
        "SUBCATEGORY_NOT_ASSIGNED": None,
        "tracks": {
            "DIRECT_SUPPLY": None,
            "EMBEDDED_MATERIAL": None,
            "DESIGN_REQUIREMENT": None,
            "DESIGN_INFLUENCE": None,
            "NO_COMMERCIAL_ENTRY": None,
            "UNKNOWN": None,
        },
    }

    medals = getattr(snap, "candidate_medal_stage", None) or {
        "state": routing_state.value,
        "computed_without_second_model_call": True,
        "CANDIDATE_GOLD": None,
        "CANDIDATE_SILVER": None,
        "CANDIDATE_BRONZE": None,
        "CANDIDATE_NONE_REVIEW": None,
    }

    return {
        "s7_source": {
            "badge": "SOURCE: S7 tender_monitor",
            "label": "S7 SOURCE TRUTH",
            "S7_OPEN_TOTAL": s7_open,
            "S7_WAITING_TOTAL": s7_waiting,
            "S7_AWARDED_FULL_HISTORY_TOTAL": s7_awarded_full,
            "by_44_223": {
                "open_44": int(snap.source_44_open or 0),
                "open_223": int(snap.source_223_open or 0),
                "waiting_44": int(snap.source_44_waiting or 0),
                "waiting_223": int(snap.source_223_waiting or 0),
                "awarded_44": int(snap.source_44_awarded_all or 0),
                "awarded_223": int(snap.source_223_awarded_all or 0),
            },
            "explanation": (
                "S7 OPEN = open-table rows with active/unknown submission deadline (end_date). "
                "S7 WAITING = commission_work + open-table rows with end_date already past. "
                "Не ждать daily-status-migration для CRM lifecycle."
            ),
        },
        "s13_projected": {
            "badge": "SOURCE: S13 crm",
            "label": "S13 PROJECTED",
            "PROJECTED_OPEN": projected_open,
            "PROJECTED_WAITING": projected_waiting,
            "PROJECTED_AWARDED_RELEVANT": projected_awarded,
            "FULL_HISTORICAL_AWARDED_IGNORED": excluded,
            "PROJECTED_TOTAL": int(snap.crm_projected or 0),
            "explanation": (
                f"S7 разыгранные (полная история)={s7_awarded_full}; "
                f"S13 разыгранные (допущены в CRM)={projected_awarded}; "
                f"исключено исторических={excluded}. "
                "OPEN/WAITING на S13 — через канонический temporal lifecycle normalizer "
                "(end_date + source_table), не только физическая таблица."
            ),
        },
        "okpd_context": {
            "badge": "SOURCE: S13 crm",
            "label": "OKPD CONTEXT (вход, не commercial category)",
            **okpd,
            "explanation": (
                "Бизнес-контекст OKPD на projected строках до V3 routing. "
                "SOURCE_TRUE_OKPD_MISSING = S7 okpd_id NULL; "
                "PROJECTION_OKPD_ERROR = S7 has OKPD but S13 null/mismatch."
            ),
        },
        "qwen_routing": {
            "badge": "SOURCE: S13 crm",
            "label": "QWEN ROUTING",
            "model": "qwen2.5:7b",
            "state": routing_state.value,
            **{k: v for k, v in routing.items() if k != "model"},
            "explanation": "Только V3 routing. Legacy procurement_ai_assessments не считаются completion.",
        },
        "commercial_opportunities": {
            "badge": "SOURCE: S13 crm",
            "label": "COMMERCIAL OPPORTUNITIES",
            "state": commercial.get("state", routing_state.value),
            **{k: v for k, v in commercial.items() if k != "state"},
            "explanation": "Production crm_procurement_category_opportunities.",
        },
        "candidate_medal": {
            "badge": "SOURCE: S13 crm",
            "label": "CANDIDATE MEDAL",
            "state": medals.get("state", routing_state.value),
            "computed_without_second_model_call": True,
            **{k: v for k, v in medals.items() if k not in ("state", "computed_without_second_model_call")},
            "explanation": "Medal считается runtime внутри track, без второго AI call.",
        },
        "document_research": {
            "badge": "SOURCE: S13 document_intelligence",
            "label": "DOCUMENT RESEARCH",
            "state": docs_state.value,
            "RESEARCH_ELIGIBLE": None,
            "QUEUE_CREATED": None,
            "DOCUMENTS_DISCOVERED": None,
            "DOCUMENTS_DOWNLOADED": None,
            "DOCUMENTS_PARSED": None,
            "EVIDENCE_FOUND": None,
            "explanation": "Document pipeline выключен — NOT STARTED (не нули).",
        },
        "confirmed_medal": {
            "badge": "SOURCE: S13 crm",
            "label": "CONFIRMED MEDAL",
            "state": confirmed_state.value,
            "CONFIRMED_GOLD": None,
            "CONFIRMED_SILVER": None,
            "CONFIRMED_BRONZE": None,
            "CONFIRMED_REJECTED": None,
            "CONFIRMED_REVIEW": None,
            "explanation": "Post-doc confirmation выключен — NOT STARTED.",
        },
    }


def _classify_crm_null_okpd_vs_s7(crm_db, tender_db, _safe_query) -> Dict[str, int]:
    """Split CRM null-OKPD rows into true source null vs projection field loss."""
    out = {"SOURCE_TRUE_OKPD_MISSING": 0, "PROJECTION_OKPD_ERROR": 0, "UNRESOLVED": 0}
    if tender_db is None:
        return out
    null_rows = _safe_query(
        crm_db,
        """
        SELECT source_table, source_id
        FROM crm_procurements
        WHERE okpd_code IS NULL OR btrim(okpd_code) = ''
        """,
    )
    by_table: Dict[str, list] = {}
    for r in null_rows or []:
        table = str(r.get("source_table") or "")
        try:
            sid = int(r.get("source_id"))
        except (TypeError, ValueError):
            out["UNRESOLVED"] += 1
            continue
        by_table.setdefault(table, []).append(sid)
    for table, ids in by_table.items():
        for i in range(0, len(ids), 2000):
            chunk = ids[i : i + 2000]
            sql = f"""
                SELECT c.id AS source_id, c.okpd_id, o.sub_code AS okpd_code
                FROM {table} c
                LEFT JOIN collection_codes_okpd o ON o.id = c.okpd_id
                WHERE c.id = ANY(%s)
            """
            try:
                s7_rows = tender_db.execute_query(sql, (chunk,)) or []
            except Exception:
                out["UNRESOLVED"] += len(chunk)
                continue
            seen = set()
            for row in s7_rows:
                if isinstance(row, dict):
                    sid = int(row["source_id"])
                    code = str(row.get("okpd_code") or "").strip()
                    okpd_id = row.get("okpd_id")
                else:
                    sid = int(row[0])
                    okpd_id = row[1]
                    code = str(row[2] or "").strip()
                seen.add(sid)
                if code:
                    out["PROJECTION_OKPD_ERROR"] += 1
                elif okpd_id is not None:
                    # Broken FK: okpd_id set but collection_codes_okpd miss — treat as projection defect class.
                    out["PROJECTION_OKPD_ERROR"] += 1
                else:
                    out["SOURCE_TRUE_OKPD_MISSING"] += 1
            for sid in chunk:
                if sid not in seen:
                    out["UNRESOLVED"] += 1
    return out


def enrich_level_a_projection(snap, crm_db, _scalar, _safe_query, tender_db=None) -> None:
    """Fill S13 projection / OKPD context / routing pending onto snapshot."""
    snap.crm_projected = _scalar(crm_db, "SELECT count(*) FROM crm_procurements")
    for row in _safe_query(
        crm_db,
        "SELECT crm_stage AS stage, count(*) AS c FROM crm_procurements GROUP BY 1",
    ):
        stg = str(row.get("stage") or "")
        c = int(row.get("c") or 0)
        if stg == "torgi":
            snap.crm_torgi = c
        elif stg == "razygranye":
            snap.crm_razygranye = c
        elif stg == "commission":
            snap.crm_commission = c

    life_rows = _safe_query(
        crm_db,
        """
        SELECT
          count(*) FILTER (
            WHERE source_table ILIKE '%%awarded%%'
               OR crm_stage = 'razygranye'
               OR award_status = 'awarded'
          ) AS awarded,
          count(*) FILTER (
            WHERE (
                 source_table ILIKE '%%commission%%'
              OR crm_stage = 'commission'
              OR award_status IN ('award_not_found', 'commission', 'submission_closed_waiting_award')
              OR (
                    crm_stage = 'torgi'
                AND end_date IS NOT NULL
                AND end_date < CURRENT_DATE
                AND NOT (
                     source_table ILIKE '%%awarded%%'
                  OR crm_stage = 'razygranye'
                  OR award_status = 'awarded'
                )
              )
            )
            AND NOT (
                 source_table ILIKE '%%awarded%%'
              OR crm_stage = 'razygranye'
              OR award_status = 'awarded'
            )
          ) AS waiting,
          count(*) FILTER (
            WHERE (
                 crm_stage = 'torgi'
              OR (
                    source_table ILIKE 'reestr_contract_%%'
                AND source_table NOT ILIKE '%%commission%%'
                AND source_table NOT ILIKE '%%awarded%%'
              )
            )
            AND COALESCE(award_status, '') NOT IN ('award_not_found', 'commission', 'awarded', 'submission_closed_waiting_award')
            AND NOT (end_date IS NOT NULL AND end_date < CURRENT_DATE)
            AND NOT (
                 source_table ILIKE '%%awarded%%'
              OR crm_stage = 'razygranye'
              OR award_status = 'awarded'
              OR source_table ILIKE '%%commission%%'
              OR crm_stage = 'commission'
            )
          ) AS open_n
        FROM crm_procurements
        """,
    )
    if life_rows:
        snap.projected_awarded_relevant = int(life_rows[0].get("awarded") or 0)
        snap.projected_waiting = int(life_rows[0].get("waiting") or 0)
        snap.projected_open = int(life_rows[0].get("open_n") or 0)
    else:
        snap.projected_open = snap.crm_torgi
        snap.projected_waiting = snap.crm_commission
        snap.projected_awarded_relevant = snap.crm_razygranye

    snap.full_historical_awarded_ignored = max(
        0, int(snap.s7_awarded_full_history_total or 0) - int(snap.projected_awarded_relevant or 0)
    )
    snap.crm_okpd_nonnull = _scalar(
        crm_db,
        "SELECT count(*) FROM crm_procurements "
        "WHERE okpd_code IS NOT NULL AND btrim(okpd_code) <> ''",
    )
    snap.crm_okpd_null = max(0, snap.crm_projected - snap.crm_okpd_nonnull)

    okpd_rows = _safe_query(
        crm_db,
        """
        SELECT
          count(*) FILTER (
            WHERE okpd_code IS NULL OR btrim(okpd_code) = ''
          ) AS missing,
          count(*) FILTER (
            WHERE okpd_code LIKE '41.%%' OR okpd_code LIKE '42.%%' OR okpd_code LIKE '43.%%'
          ) AS construction,
          count(*) FILTER (
            WHERE okpd_code LIKE '71.%%' OR okpd_code LIKE '74.%%'
          ) AS design_pir,
          count(*) FILTER (
            WHERE okpd_code LIKE '26.20%%' OR okpd_code LIKE '26.2%%'
          ) AS computers,
          count(*) FILTER (
            WHERE okpd_code LIKE '27.40%%' OR okpd_code LIKE '27.4%%'
          ) AS lighting
        FROM crm_procurements
        """,
    )
    if okpd_rows:
        r = okpd_rows[0]
        missing = int(r.get("missing") or 0)
        construction = int(r.get("construction") or 0)
        design = int(r.get("design_pir") or 0)
        computers = int(r.get("computers") or 0)
        lighting = int(r.get("lighting") or 0)
        known = construction + design + computers + lighting
        other = max(0, snap.crm_okpd_nonnull - known)
        snap.okpd_business_funnel = {
            "CONSTRUCTION_OKPD": construction,
            "DESIGN_PIR_OKPD": design,
            "COMPUTERS_OKPD": computers,
            "LIGHTING_OKPD": lighting,
            "OTHER_OKPD": other,
            "MISSING_OKPD": missing,
            "SOURCE_TRUE_OKPD_MISSING": missing,
            "PROJECTION_OKPD_ERROR": 0,
        }
        split = _classify_crm_null_okpd_vs_s7(crm_db, tender_db, _safe_query)
        if tender_db is not None:
            snap.okpd_business_funnel["SOURCE_TRUE_OKPD_MISSING"] = int(
                split.get("SOURCE_TRUE_OKPD_MISSING") or 0
            )
            snap.okpd_business_funnel["PROJECTION_OKPD_ERROR"] = int(
                split.get("PROJECTION_OKPD_ERROR") or 0
            )
            snap.okpd_business_funnel["OKPD_SOURCE_UNRESOLVED"] = int(split.get("UNRESOLVED") or 0)


    snap.ai_routing_stages = {
        "PENDING_ROUTING": int(snap.crm_projected or 0),
        "SENT_TO_MODEL": 0,
        "ROUTING_COMPLETED": 0,
        "ROUTING_FAILED": 0,
        "REVIEW_REQUIRED": 0,
        "UNKNOWN": 0,
        "model": "qwen2.5:7b",
        "legacy_ai_assessments_excluded": True,
    }
    snap.commercial_result = {
        "state": "NOT_STARTED",
        "CATEGORY_ASSIGNED": None,
        "SUBCATEGORY_ASSIGNED": None,
        "SUBCATEGORY_NOT_ASSIGNED": None,
        "tracks": {
            "DIRECT_SUPPLY": None,
            "EMBEDDED_MATERIAL": None,
            "DESIGN_REQUIREMENT": None,
            "DESIGN_INFLUENCE": None,
            "NO_COMMERCIAL_ENTRY": None,
            "UNKNOWN": None,
        },
    }
    snap.candidate_medal_stage = {
        "state": "NOT_STARTED",
        "computed_without_second_model_call": True,
        "CANDIDATE_GOLD": None,
        "CANDIDATE_SILVER": None,
        "CANDIDATE_BRONZE": None,
        "CANDIDATE_NONE_REVIEW": None,
    }
