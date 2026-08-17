"""Build canonical pre-model procurement card (S13 cache + S7 RO enrich).

Card version V2. Does not call LLM. Does not download documents.

Date semantics:
  source_created_at = ingestion/source-presence only — NEVER renamed to published_at.
  published_at = only when source explicitly provides publication date; else NULL.
  OPEN source start_date/end_date = procedure window (submission), NOT proven publication.
  AWARDED start_date/end_date are often contract execution window; NOT submission.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.deadline_pressure import (
    DEADLINE_PRESSURE_FORMULA,
    DEADLINE_PRESSURE_VERSION,
    compute_tender_clock,
)
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.commercial_routing_v3.prior_semantics import (
    DIRECT_CABLE_EXPECTED_RESULT,
    split_matched_priors,
)
from src.services.commercial_routing_v3.source_contour import resolve_source_contour
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_event,
)

CARD_VERSION = "V1"
V3_ROUTING_MODEL_INPUT_VERSION = "V3_ROUTING_MODEL_INPUT_V3"


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    s = str(v).strip()
    return s or None


def infer_source_origin(
    *,
    source_created_at: Any,
    start_date: Any,
    end_date: Any,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Transparent heuristic — not a claim of parser mode.

    FORWARD_NEW: created near publication window
    BACKWARD_RECOVERED: created_at substantially after start_date
    UNKNOWN: insufficient evidence
    RGK_RECOVERED: not inferred without ingestion_run metadata
    """

    def _d(x):
        if x is None:
            return None
        if hasattr(x, "date"):
            try:
                return x.date()
            except Exception:
                pass
        if hasattr(x, "year") and not hasattr(x, "hour"):
            return x
        try:
            return date.fromisoformat(str(x)[:10])
        except Exception:
            return None

    created = _d(source_created_at)
    start = _d(start_date)
    if created is None:
        return {
            "source_origin": "UNKNOWN",
            "is_forward_new": False,
            "is_backward_recovered": False,
            "is_rgk_recovered": False,
            "source_origin_provenance": "SOURCE_NOT_AVAILABLE",
        }
    if start and (created - start).days >= 14:
        return {
            "source_origin": "BACKWARD_RECOVERED",
            "is_forward_new": False,
            "is_backward_recovered": True,
            "is_rgk_recovered": False,
            "source_origin_provenance": "DERIVED",
        }
    if start and abs((created - start).days) <= 7:
        return {
            "source_origin": "FORWARD_NEW",
            "is_forward_new": True,
            "is_backward_recovered": False,
            "is_rgk_recovered": False,
            "source_origin_provenance": "DERIVED",
        }
    return {
        "source_origin": "UNKNOWN",
        "is_forward_new": False,
        "is_backward_recovered": False,
        "is_rgk_recovered": False,
        "source_origin_provenance": "DERIVED",
    }


def build_okpd_hierarchy(crm_or_tender_db, okpd_code: str) -> Dict[str, Any]:
    """Best-effort hierarchy via S7 collection_codes_okpd (read-only)."""
    if not okpd_code:
        return {"okpd_code": None, "okpd_name": None, "hierarchy": []}
    try:
        import os
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST") or os.getenv("TENDER_DB_HOST") or "S7",
            port=int(os.getenv("DB_PORT") or os.getenv("TENDER_DB_PORT") or 5432),
            dbname=os.getenv("DB_NAME") or os.getenv("TENDER_DB_DATABASE") or "tender_monitor",
            user=os.getenv("DB_USER") or os.getenv("TENDER_DB_USER"),
            password=os.getenv("DB_PASSWORD") or os.getenv("TENDER_DB_PASSWORD") or "",
            connect_timeout=8,
        )
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SET default_transaction_read_only = on")
                cur.execute(
                    """
                    WITH RECURSIVE climb AS (
                      SELECT id, sub_code, main_code, parent_id, name, 0 AS depth
                      FROM collection_codes_okpd WHERE sub_code = %s
                      UNION ALL
                      SELECT p.id, p.sub_code, p.main_code, p.parent_id, p.name, c.depth+1
                      FROM collection_codes_okpd p
                      JOIN climb c ON p.id = c.parent_id
                      WHERE c.depth < 8
                    )
                    SELECT id, sub_code, main_code, parent_id, name, depth
                    FROM climb ORDER BY depth
                    """,
                    (okpd_code,),
                )
                chain = [dict(r) for r in (cur.fetchall() or [])]
        finally:
            conn.close()
    except Exception:
        return {
            "okpd_code": okpd_code,
            "okpd_name": None,
            "hierarchy": [],
            "provenance": "NOT_PROJECTED",
        }
    if not chain:
        return {
            "okpd_code": okpd_code,
            "okpd_name": None,
            "hierarchy": [],
            "provenance": "SOURCE_NOT_AVAILABLE",
        }
    root = chain[-1]
    parent = chain[1] if len(chain) > 1 else None
    leaf = chain[0]
    return {
        "okpd_code": okpd_code,
        "okpd_name": leaf.get("name"),
        "okpd_parent_code": (parent or {}).get("sub_code"),
        "okpd_parent_name": (parent or {}).get("name"),
        "okpd_root_code": root.get("sub_code"),
        "okpd_root_name": root.get("name"),
        "hierarchy": [
            {"code": r.get("sub_code"), "name": r.get("name"), "depth": r.get("depth")}
            for r in chain
        ],
        "provenance": "NORMALIZED_FROM_SOURCE",
    }


def proposed_routing_priority(card: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic pre-LLM routing fields. No LLM."""
    lc = str(card.get("normalized_lifecycle") or "")
    origin = str(card.get("source_origin") or "UNKNOWN")
    pressure = card.get("deadline_pressure")
    has_product = bool(card.get("COMMERCIAL_PRODUCT_PRIORS"))
    has_context = bool(card.get("CONTEXTUAL_RESEARCH_PRIORS"))
    links = int(card.get("document_link_count") or 0)

    if lc == "OPEN" and origin == "FORWARD_NEW":
        lane = "FORWARD_ACTIVE"
        base = 900
        reason = "forward_new_open"
    elif lc == "OPEN":
        lane = "ACTIVE_CATCHUP"
        base = 700
        reason = "open_active"
    elif lc == "WAITING_SOURCE_OUTCOME":
        lane = "WAITING"
        base = 400
        reason = "waiting_source_outcome"
    elif lc == "AWARDED":
        # Product-only awarded = closed direct supply (history). Contextual/object
        # priors may still be follow-up. Do not treat OKPD prefix as the router.
        if has_context:
            lane = "AWARDED_FOLLOWUP"
            base = 300
            reason = "awarded_followup"
        elif has_product:
            lane = "AWARDED_HISTORY"
            base = 100
            reason = "awarded_direct_supply_closed"
        else:
            lane = "AWARDED_HISTORY"
            base = 100
            reason = "awarded_history"
    else:
        lane = "UNKNOWN"
        base = 50
        reason = "unknown_lifecycle"

    boost = int(float(pressure or 0) * 0.15)  # soft; never overpowers commercial lane
    if not has_product and has_context:
        reason += "+contextual_only"
        base = min(base, 550)
    if links == 0 and lc == "OPEN":
        reason += "+links_unresolved"
    return {
        "routing_lane": lane,
        "routing_priority": base + boost,
        "routing_priority_reason": reason,
        "routing_priority_version": "V1",
    }


def build_canonical_card(
    *,
    procurement: Dict[str, Any],
    priors: List[Dict[str, Any]],
    tender_db=None,
    winner: Optional[Dict[str, Any]] = None,
    resolve_links: bool = True,
) -> Dict[str, Any]:
    pid = int(procurement["id"])
    source_table = str(procurement.get("source_table") or "")
    source_id = procurement.get("source_id")
    contract_number = procurement.get("contract_number")
    contour = resolve_source_contour(source_table=source_table)
    lifecycle = normalize_source_lifecycle_event(
        source_table=source_table,
        crm_stage=str(procurement.get("crm_stage") or ""),
        award_status=str(procurement.get("award_status") or ""),
        end_date=procurement.get("end_date"),
    )
    is_awarded = lifecycle.value == "AWARDED"

    if is_awarded:
        # Do not misuse contract dates as submission window
        published_at = procurement.get("published_at")  # only if enriched/explicit
        submission_start_at = procurement.get("submission_start_at")
        submission_deadline_at = procurement.get("submission_deadline_at")
        contract_signed_at = procurement.get("contract_signed_at") or procurement.get("start_date")
        exec_start = (
            procurement.get("execution_start_at")
            or procurement.get("delivery_start_date")
            or procurement.get("start_date")
        )
        exec_end = (
            procurement.get("execution_end_at")
            or procurement.get("delivery_end_date")
            or procurement.get("end_date")
        )
        award_at = procurement.get("award_date") or procurement.get("start_date")
        pub_prov = (
            "NORMALIZED_FROM_SOURCE:published_at"
            if published_at
            else "SOURCE_NOT_AVAILABLE"
        )
        sub_prov = (
            "NORMALIZED_FROM_SOURCE:submission_start_at"
            if submission_start_at
            else "SOURCE_NOT_AVAILABLE"
        )
        dl_prov = (
            "NORMALIZED_FROM_SOURCE:submission_deadline_at"
            if submission_deadline_at
            else "SOURCE_NOT_AVAILABLE"
        )
        proc_start = submission_start_at
        proc_end = submission_deadline_at
        proc_start_prov = sub_prov
        proc_end_prov = dl_prov
    else:
        # OPEN: never fabricate published_at from generic start_date.
        published_at = procurement.get("published_at") or procurement.get("publication_date")
        if published_at:
            pub_prov = "NORMALIZED_FROM_SOURCE:published_at"
        else:
            published_at = None
            pub_prov = "SOURCE_NOT_AVAILABLE"

        # Generic EIS start_date/end_date = procedure/application window (not publication).
        submission_start_at = procurement.get("submission_start_at") or procurement.get(
            "start_date"
        )
        submission_deadline_at = procurement.get("submission_deadline_at") or procurement.get(
            "end_date"
        )
        sub_prov = (
            "NORMALIZED_FROM_SOURCE:submission_start_at"
            if procurement.get("submission_start_at")
            else (
                "NORMALIZED_FROM_SOURCE:start_date_AS_PROCEDURE_START"
                if procurement.get("start_date")
                else "SOURCE_NOT_AVAILABLE"
            )
        )
        dl_prov = (
            "NORMALIZED_FROM_SOURCE:submission_deadline_at"
            if procurement.get("submission_deadline_at")
            else (
                "NORMALIZED_FROM_SOURCE:end_date_AS_PROCEDURE_END"
                if procurement.get("end_date")
                else "SOURCE_NOT_AVAILABLE"
            )
        )
        contract_signed_at = procurement.get("contract_signed_at")
        exec_start = procurement.get("execution_start_at") or procurement.get(
            "delivery_start_date"
        )
        exec_end = procurement.get("execution_end_at") or procurement.get(
            "delivery_end_date"
        )
        award_at = procurement.get("award_date")
        proc_start = submission_start_at
        proc_end = submission_deadline_at
        proc_start_prov = sub_prov
        proc_end_prov = dl_prov

    # OPEN zero-duration DATE_ONLY (common on 223): flag, do not treat as valid active window
    invalid_zero = False
    if not is_awarded and submission_start_at and submission_deadline_at:
        try:
            if str(submission_start_at)[:10] == str(submission_deadline_at)[:10]:
                invalid_zero = True
        except Exception:
            pass

    # Tender clock uses procedure dates; published_at only if truly available (may be NULL).
    clock = compute_tender_clock(
        published_at=published_at,
        submission_start_at=submission_start_at,
        submission_deadline_at=submission_deadline_at,
        active_urgency=(lifecycle.value == "OPEN" and not invalid_zero),
        date_precision="DATE_ONLY",
    )
    # Origin compares ingestion time vs procedure start — not fabricated publication.
    origin_start = submission_start_at or procurement.get("start_date")
    origin = infer_source_origin(
        source_created_at=procurement.get("source_created_at")
        or procurement.get("crm_created_at"),
        start_date=origin_start,
        end_date=submission_deadline_at or procurement.get("end_date"),
    )
    okpd_code = procurement.get("okpd_code")
    hierarchy = {"okpd_code": okpd_code, "okpd_name": procurement.get("okpd_name")}
    if tender_db is not None and okpd_code:
        hierarchy = build_okpd_hierarchy(tender_db, str(okpd_code))
        if not hierarchy.get("okpd_name"):
            hierarchy["okpd_name"] = procurement.get("okpd_name")
    ancestry = [
        str(item.get("code") or "")
        for item in (hierarchy.get("hierarchy") or [])
        if isinstance(item, dict) and item.get("code")
    ]
    prior_split = split_matched_priors(
        str(okpd_code or ""), priors, ancestry_codes=ancestry or None
    )
    links = (
        resolve_document_links(
            source_table=source_table,
            source_id=int(source_id) if source_id is not None else None,
            contract_number=str(contract_number) if contract_number else None,
        )
        if resolve_links
        else {"links": [], "link_count": 0, "unique_url_count": 0}
    )

    customer_name = procurement.get("customer")
    customer_inn = procurement.get("customer_inn") or procurement.get("placer_inn")
    delivery_region = procurement.get("delivery_region")
    delivery_address = procurement.get("delivery_address")
    region_id = procurement.get("region_id") or procurement.get("source_region_id")

    primary_region = delivery_region
    primary_region_source = "SOURCE_DELIVERY_REGION" if delivery_region else "UNKNOWN"
    if not primary_region and procurement.get("region_name"):
        primary_region = procurement.get("region_name")
        primary_region_source = "SOURCE_REGION_ID"

    initial = procurement.get("initial_price")
    final = (
        procurement.get("final_contract_price")
        or procurement.get("final_price")
        or (winner or {}).get("final_price")
    )
    reduction_abs = reduction_pct = None
    try:
        if initial is not None and final is not None and float(initial) > 0:
            reduction_abs = float(initial) - float(final)
            reduction_pct = 100.0 * reduction_abs / float(initial)
    except Exception:
        pass

    w_name = (winner or {}).get("winner_name") or procurement.get("winner_name") or procurement.get(
        "contractor_name"
    )
    w_inn = (winner or {}).get("winner_inn") or procurement.get("winner_inn") or procurement.get(
        "contractor_inn"
    )

    card: Dict[str, Any] = {
        "card_version": "V2",
        "date_precision": "DATE_ONLY",
        "invalid_zero_duration": invalid_zero,
        "source_start_date": _iso(procurement.get("start_date")),
        "source_end_date": _iso(procurement.get("end_date")),
        "source_delivery_start_date": _iso(procurement.get("delivery_start_date")),
        "source_delivery_end_date": _iso(procurement.get("delivery_end_date")),
        "source_region_id": region_id,
        "source_delivery_region": delivery_region,
        "source_delivery_address": delivery_address,
        "source_okpd_id": procurement.get("source_okpd_id") or procurement.get("okpd_id"),
        "source_customer_id": procurement.get("source_customer_id") or procurement.get("customer_id"),
        "source_contractor_id": procurement.get("source_contractor_id") or procurement.get("contractor_id"),
        "source_initial_price": initial,
        "source_final_price": procurement.get("final_price"),
        "source_tender_link": procurement.get("tender_link"),
        "procurement_start_at": _iso(proc_start) if not is_awarded else None,
        "procurement_start_at_provenance": proc_start_prov if not is_awarded else "N/A_AWARDED",
        "procurement_end_at": _iso(proc_end) if not is_awarded else None,
        "procurement_end_at_provenance": proc_end_prov if not is_awarded else "N/A_AWARDED",
        "delivery_start_at": _iso(exec_start if is_awarded else procurement.get("delivery_start_date")),
        "delivery_end_at": _iso(exec_end if is_awarded else procurement.get("delivery_end_date")),
        "PROCUREMENT_DELIVERY_DATE_CONFLATION": 0,
        "procurement_id": pid,
        "source_contour": getattr(contour, "value", str(contour)),
        "source_table": source_table,
        "source_id": source_id,
        "procurement_number": contract_number,
        "contract_number": contract_number,
        "canonical_identity": (
            f"{getattr(contour, 'value', contour)}::{contract_number}"
            if contract_number
            else f"{getattr(contour, 'value', contour)}::{source_table}:{source_id}"
        ),
        "title": procurement.get("auction_name"),
        "official_description": procurement.get("official_description"),
        "official_description_provenance": (
            "NORMALIZED_FROM_SOURCE"
            if procurement.get("official_description")
            else "SOURCE_NOT_AVAILABLE"
        ),
        "physical_source_status": procurement.get("crm_stage") or source_table,
        "normalized_lifecycle": lifecycle.value,
        "first_seen_at": _iso(procurement.get("crm_created_at")),
        "source_created_at": _iso(procurement.get("source_created_at")),
        "source_created_at_role": "INGESTION_OR_SOURCE_PRESENCE_ONLY",
        "source_updated_at": _iso(procurement.get("source_updated_at")),
        **origin,
        "published_at": _iso(published_at),
        "published_at_provenance": pub_prov,
        "submission_start_at": _iso(submission_start_at),
        "submission_start_provenance": sub_prov,
        "submission_deadline_at": _iso(submission_deadline_at),
        "submission_deadline_provenance": dl_prov,
        "award_at": _iso(award_at),
        "contract_signed_at": _iso(contract_signed_at),
        "contract_execution_start_at": _iso(exec_start),
        "contract_execution_end_at": _iso(exec_end),
        "tender_clock": clock.to_dict(),
        "total_duration_days": (
            (clock.total_duration_hours / 24.0) if clock.total_duration_hours is not None else None
        ),
        "elapsed_days": (
            (clock.elapsed_seconds / 86400.0) if clock.elapsed_seconds is not None else None
        ),
        "remaining_days": clock.remaining_days,
        "elapsed_ratio": clock.elapsed_ratio,
        "remaining_ratio": clock.remaining_ratio,
        "deadline_pressure": clock.deadline_pressure,
        "deadline_pressure_version": DEADLINE_PRESSURE_VERSION,
        "deadline_pressure_formula": DEADLINE_PRESSURE_FORMULA,
        "customer_name": customer_name,
        "customer_inn": customer_inn,
        "customer_kpp": procurement.get("customer_kpp"),
        "customer_provenance": (
            "NORMALIZED_FROM_SOURCE:customer|placer" if customer_name else "SOURCE_NOT_AVAILABLE"
        ),
        "purchasing_organization_name": procurement.get("purchasing_organization_name"),
        "purchasing_organization_inn": procurement.get("purchasing_organization_inn"),
        "purchasing_organization_provenance": (
            "NORMALIZED_FROM_SOURCE"
            if procurement.get("purchasing_organization_name")
            else "SOURCE_NOT_AVAILABLE"
        ),
        "balance_holder_name": None,
        "balance_holder_inn": None,
        "balance_holder_provenance": "SOURCE_NOT_AVAILABLE",
        "beneficiary_name": None,
        "operator_name": None,
        "winner_name": w_name if is_awarded else None,
        "winner_inn": w_inn if is_awarded else None,
        "winner_kpp": (winner or {}).get("winner_kpp") if is_awarded else None,
        "winner_role": ("SUPPLIER" if (is_awarded and w_name) else None),
        "winner_provenance": (
            "NORMALIZED_FROM_SOURCE:contractor"
            if (is_awarded and w_name)
            else ("N/A_NOT_AWARDED" if not is_awarded else "SOURCE_NOT_AVAILABLE")
        ),
        "object_name": None,
        "object_region": None,
        "object_address": delivery_address,
        "delivery_region": delivery_region,
        "delivery_address": delivery_address,
        "performance_region": delivery_region,
        "performance_address": delivery_address,
        "primary_commercial_region": primary_region,
        "primary_commercial_region_source": primary_region_source,
        "initial_price": initial,
        "final_contract_price": final if is_awarded else None,
        "price_reduction_absolute": reduction_abs if is_awarded else None,
        "price_reduction_percent": reduction_pct if is_awarded else None,
        "okpd": hierarchy,
        "okpd_code": hierarchy.get("okpd_code") or okpd_code,
        "okpd_name": hierarchy.get("okpd_name") or procurement.get("okpd_name"),
        "COMMERCIAL_PRODUCT_PRIORS": [
            {
                "category": p.get("commercial_category_code"),
                "okpd_pattern": p.get("okpd_pattern"),
                "weight": float(p.get("prior_weight") or 0),
                "prior_kind": p.get("prior_kind"),
                "match_type": p.get("match_type"),
                "evidence_role": "COMMERCIAL_PRODUCT_PRIOR",
            }
            for p in prior_split["COMMERCIAL_PRODUCT_PRIORS"]
        ],
        "CONTEXTUAL_RESEARCH_PRIORS": [
            {
                "category": p.get("commercial_category_code"),
                "okpd_pattern": p.get("okpd_pattern"),
                "weight": float(p.get("prior_weight") or 0),
                "prior_kind": p.get("prior_kind"),
            }
            for p in prior_split["CONTEXTUAL_RESEARCH_PRIORS"]
        ],
        "DIRECT_CABLE_EXPECTED_RESULT": DIRECT_CABLE_EXPECTED_RESULT,
        "source_card_url": procurement.get("tender_link"),
        "source_card_url_type": "tender_link",
        "source_card_url_provenance": (
            "NORMALIZED_FROM_SOURCE:tender_link"
            if procurement.get("tender_link")
            else "SOURCE_NOT_AVAILABLE"
        ),
        "document_link_count": links.get("unique_physical_download_target_count")
        or links.get("link_count")
        or 0,
        "raw_document_link_count": links.get("raw_document_link_count") or links.get("link_count") or 0,
        "unique_document_url_count": links.get("unique_document_url_count")
        or links.get("unique_url_count")
        or 0,
        "unique_source_document_id_count": links.get("unique_source_document_id_count") or 0,
        "unique_physical_download_target_count": links.get("unique_physical_download_target_count") or 0,
        "duplicate_physical_download_targets": links.get("duplicate_physical_download_targets") or 0,
        "document_links_summary": [
            {"name": l.get("document_name"), "url": l.get("document_url")}
            for l in (links.get("links") or [])[:20]
        ],
        "document_link_resolution_method": links.get("resolution_method"),
        "commercial_target_role": None,
        "commercial_target_name": None,
        "commercial_target_inn": None,
        "commercial_target_reason": "NOT_POPULATED_UNTIL_TRACK_KNOWN",
        "model_input_version": V3_ROUTING_MODEL_INPUT_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    # execution_active for awarded
    if is_awarded and exec_end:
        try:
            from datetime import date as _date

            card["execution_active"] = _date.fromisoformat(str(exec_end)[:10]) >= _date.today()
        except Exception:
            card["execution_active"] = None
    else:
        card["execution_active"] = None

    card.update(proposed_routing_priority(card))
    from src.services.commercial_routing_v3.routing_ready import evaluate_routing_ready
    from src.services.commercial_routing_v3.commercial_timing import attach_commercial_timing

    card.update(evaluate_routing_ready(card))
    attach_commercial_timing(card)
    return card


def upsert_canonical_card(crm_db, card: Dict[str, Any]) -> None:
    crm_db.execute_update(
        """
        INSERT INTO crm_v3_canonical_procurement_cards
            (procurement_id, card_json, card_version, source_fingerprint, built_at, updated_at)
        VALUES (%s, %s::jsonb, %s, %s, now(), now())
        ON CONFLICT (procurement_id) DO UPDATE SET
            card_json = EXCLUDED.card_json,
            card_version = EXCLUDED.card_version,
            source_fingerprint = EXCLUDED.source_fingerprint,
            built_at = EXCLUDED.built_at,
            updated_at = now()
        """,
        (
            int(card["procurement_id"]),
            __import__("json").dumps(card, ensure_ascii=False, default=str),
            card.get("card_version") or CARD_VERSION,
            card.get("canonical_identity"),
        ),
    )
