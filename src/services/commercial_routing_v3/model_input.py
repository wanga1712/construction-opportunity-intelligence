"""Explicit V3 routing model input built from canonical procurement card.

Version: V3_ROUTING_MODEL_INPUT_V3

This is the ONLY semantic object that may be serialized into the 7B prompt
for production V3 routing. Do not pass raw CRM SELECT rows to the model.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from src.services.commercial_routing_v3.canonical_card import (
    V3_ROUTING_MODEL_INPUT_VERSION,
)

# Keys allowed in the frozen model-input object (compact; no link arrays / XML).
_MODEL_INPUT_KEYS = (
    "model_input_version",
    "procurement_id",
    "procurement_number",
    "source_contour",
    "source_table",
    "source_id",
    "source_origin",
    "title",
    "official_description",
    "normalized_lifecycle",
    "source_start_date",
    "source_end_date",
    "procurement_start_at",
    "procurement_end_at",
    "procurement_start_at_provenance",
    "procurement_end_at_provenance",
    "published_at",
    "published_at_provenance",
    "source_created_at",
    "procurement_duration_days",
    "remaining_days",
    "remaining_ratio",
    "deadline_pressure",
    "procurement_age_days",
    "award_age_days",
    "execution_remaining_days",
    "commercial_timing_value",
    "commercial_timing_version",
    "commercial_timing_confidence",
    "commercial_timing_start_provenance",
    "source_delivery_start_date",
    "source_delivery_end_date",
    "delivery_start_at",
    "delivery_end_at",
    "customer_name",
    "customer_inn",
    "purchasing_organization",
    "winner_name",
    "winner_inn",
    "winner_role",
    "award_at",
    "initial_price",
    "final_contract_price",
    "price_reduction_percent",
    "contract_execution_end_at",
    "execution_active",
    "primary_commercial_region",
    "region_provenance",
    "okpd_codes",
    "okpd_names",
    "okpd_hierarchy",
    "COMMERCIAL_PRODUCT_PRIORS",
    "CONTEXTUAL_RESEARCH_PRIORS",
    "DIRECT_CABLE_EXPECTED_RESULT",
    "source_card_url",
    "source_card_url_type",
    "document_link_count",
    "unique_document_count",
)


def _trim_desc(text: Any, limit: int = 800) -> Optional[str]:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    return s if len(s) <= limit else (s[: limit - 1] + "…")


def _okpd_lists(card: Dict[str, Any]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    codes: List[str] = []
    names: List[str] = []
    hier: List[Dict[str, Any]] = []
    okpd = card.get("okpd") if isinstance(card.get("okpd"), dict) else {}
    code = card.get("okpd_code") or (okpd or {}).get("okpd_code")
    name = card.get("okpd_name") or (okpd or {}).get("okpd_name")
    if code:
        codes.append(str(code))
        names.append(str(name or ""))
    for item in (okpd or {}).get("hierarchy") or []:
        if isinstance(item, dict):
            hier.append(
                {
                    "code": item.get("code") or item.get("okpd_code"),
                    "name": item.get("name") or item.get("okpd_name"),
                }
            )
            c = item.get("code") or item.get("okpd_code")
            if c and str(c) not in codes:
                codes.append(str(c))
                names.append(str(item.get("name") or item.get("okpd_name") or ""))
    # multi-OKPD field if present on card
    for extra in card.get("okpd_codes") or card.get("exact_okpd_codes") or []:
        if extra and str(extra) not in codes:
            codes.append(str(extra))
    return codes, names, hier


def build_v3_routing_model_input(canonical_card: Dict[str, Any]) -> Dict[str, Any]:
    """Build serializable V3_ROUTING_MODEL_INPUT_V3 from a canonical card."""
    card = canonical_card or {}
    codes, names, hier = _okpd_lists(card)
    commercial = list(card.get("COMMERCIAL_PRODUCT_PRIORS") or [])
    contextual = list(card.get("CONTEXTUAL_RESEARCH_PRIORS") or [])
    # Compact priors: category + pattern + kind only
    def _prior_row(p: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "category": p.get("category") or p.get("commercial_category_code"),
            "okpd_pattern": p.get("okpd_pattern"),
            "weight": float(p.get("weight") or p.get("prior_weight") or 0),
            "prior_kind": p.get("prior_kind"),
            "match_type": p.get("match_type"),
            "evidence_role": p.get("evidence_role") or p.get("prior_kind"),
            "matched_okpd_branch_root_code": p.get("matched_okpd_branch_root_code")
            or p.get("okpd_pattern"),
        }

    mi: Dict[str, Any] = {
        "model_input_version": V3_ROUTING_MODEL_INPUT_VERSION,
        "procurement_id": card.get("procurement_id"),
        "procurement_number": card.get("procurement_number") or card.get("contract_number"),
        "source_contour": card.get("source_contour"),
        "source_table": card.get("source_table"),
        "source_id": card.get("source_id"),
        "source_origin": card.get("source_origin") or "UNKNOWN",
        "title": card.get("title"),
        "official_description": _trim_desc(card.get("official_description")),
        "normalized_lifecycle": card.get("normalized_lifecycle"),
        "source_start_date": card.get("source_start_date"),
        "source_end_date": card.get("source_end_date"),
        "procurement_start_at": card.get("procurement_start_at"),
        "procurement_end_at": card.get("procurement_end_at"),
        "procurement_start_at_provenance": card.get("procurement_start_at_provenance"),
        "procurement_end_at_provenance": card.get("procurement_end_at_provenance"),
        "published_at": card.get("published_at"),
        "published_at_provenance": card.get("published_at_provenance"),
        "source_created_at": card.get("source_created_at"),
        "procurement_duration_days": card.get("procurement_duration_days")
        or card.get("tender_duration_days"),
        "remaining_days": card.get("remaining_days"),
        "remaining_ratio": card.get("remaining_ratio"),
        "deadline_pressure": card.get("deadline_pressure"),
        "procurement_age_days": card.get("procurement_age_days"),
        "award_age_days": card.get("award_age_days"),
        "execution_remaining_days": card.get("execution_remaining_days"),
        "commercial_timing_value": card.get("commercial_timing_value"),
        "commercial_timing_version": card.get("commercial_timing_version"),
        "commercial_timing_confidence": card.get("commercial_timing_confidence"),
        "commercial_timing_start_provenance": card.get(
            "commercial_timing_start_provenance"
        ),
        "source_delivery_start_date": card.get("source_delivery_start_date"),
        "source_delivery_end_date": card.get("source_delivery_end_date"),
        "delivery_start_at": card.get("delivery_start_at"),
        "delivery_end_at": card.get("delivery_end_at"),
        "customer_name": card.get("customer_name") or card.get("customer"),
        "customer_inn": card.get("customer_inn"),
        "purchasing_organization": card.get("purchasing_organization")
        or card.get("customer_name")
        or card.get("customer"),
        "winner_name": card.get("winner_name"),
        "winner_inn": card.get("winner_inn"),
        "winner_role": card.get("winner_role"),
        "award_at": card.get("award_at"),
        "initial_price": card.get("initial_price"),
        "final_contract_price": card.get("final_contract_price"),
        "price_reduction_percent": card.get("price_reduction_percent"),
        "contract_execution_end_at": card.get("contract_execution_end_at")
        or card.get("delivery_end_at"),
        "execution_active": card.get("execution_active"),
        "primary_commercial_region": card.get("primary_commercial_region"),
        "region_provenance": card.get("primary_commercial_region_source")
        or card.get("region_provenance"),
        "okpd_codes": codes,
        "okpd_names": names,
        "okpd_hierarchy": hier[:12],
        "COMMERCIAL_PRODUCT_PRIORS": [_prior_row(p) for p in commercial],
        "CONTEXTUAL_RESEARCH_PRIORS": [_prior_row(p) for p in contextual],
        "DIRECT_CABLE_EXPECTED_RESULT": card.get("DIRECT_CABLE_EXPECTED_RESULT"),
        "source_card_url": card.get("source_card_url"),
        "source_card_url_type": card.get("source_card_url_type"),
        "document_link_count": int(card.get("document_link_count") or 0),
        "unique_document_count": int(
            card.get("unique_document_url_count")
            or card.get("unique_physical_download_target_count")
            or card.get("unique_document_count")
            or 0
        ),
    }
    # Drop accidental document blobs if caller polluted the card
    assert "document_links_summary" not in mi
    assert "document_names_summary" not in mi
    return {k: mi.get(k) for k in _MODEL_INPUT_KEYS}


def model_input_json(model_input: Dict[str, Any]) -> str:
    return json.dumps(model_input, ensure_ascii=False, sort_keys=True, default=str)


def model_input_hash(model_input: Dict[str, Any]) -> str:
    return hashlib.sha256(model_input_json(model_input).encode("utf-8")).hexdigest()


def canonical_card_hash(card: Dict[str, Any]) -> str:
    payload = json.dumps(card, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def model_input_as_prompt_procurement(model_input: Dict[str, Any]) -> Dict[str, Any]:
    """Adapter for legacy call sites that still expect a procurement-shaped dict."""
    codes = model_input.get("okpd_codes") or []
    names = model_input.get("okpd_names") or []
    return {
        "id": model_input.get("procurement_id"),
        "procurement_id": model_input.get("procurement_id"),
        "title": model_input.get("title"),
        "auction_name": model_input.get("title"),
        "okpd_code": codes[0] if codes else None,
        "okpd_name": names[0] if names else None,
        "okpd_codes": codes,
        "price": float(model_input.get("initial_price") or 0),
        "initial_price": model_input.get("initial_price"),
        "customer": model_input.get("customer_name"),
        "customer_name": model_input.get("customer_name"),
        "customer_inn": model_input.get("customer_inn"),
        "region": model_input.get("primary_commercial_region"),
        "primary_commercial_region": model_input.get("primary_commercial_region"),
        "region_provenance": model_input.get("region_provenance"),
        "source_table": model_input.get("source_table"),
        "source_id": model_input.get("source_id"),
        "source_contour": model_input.get("source_contour"),
        "source_origin": model_input.get("source_origin"),
        "normalized_lifecycle": model_input.get("normalized_lifecycle"),
        "law_type": (
            "223_FZ"
            if "223" in str(model_input.get("source_table") or "")
            else ("615_PP" if "615" in str(model_input.get("source_table") or "") else "44_FZ")
        ),
        "procurement_start_at": model_input.get("procurement_start_at"),
        "procurement_end_at": model_input.get("procurement_end_at"),
        "delivery_start_at": model_input.get("delivery_start_at"),
        "delivery_end_at": model_input.get("delivery_end_at"),
        "winner_name": model_input.get("winner_name"),
        "winner_inn": model_input.get("winner_inn"),
        "winner_role": model_input.get("winner_role"),
        "final_contract_price": model_input.get("final_contract_price"),
        "execution_active": model_input.get("execution_active"),
        "COMMERCIAL_PRODUCT_PRIORS": model_input.get("COMMERCIAL_PRODUCT_PRIORS") or [],
        "CONTEXTUAL_RESEARCH_PRIORS": model_input.get("CONTEXTUAL_RESEARCH_PRIORS") or [],
        "DIRECT_CABLE_EXPECTED_RESULT": model_input.get("DIRECT_CABLE_EXPECTED_RESULT"),
        "document_link_count": model_input.get("document_link_count"),
        "unique_document_count": model_input.get("unique_document_count"),
        "source_card_url": model_input.get("source_card_url"),
        "v3_model_input": model_input,
        "model_input_version": model_input.get("model_input_version"),
    }


def audit_model_input_required_fields(
    model_input: Dict[str, Any],
    *,
    source_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Lifecycle-aware mandatory-field audit.

    OPEN / ACTIVE / FORWARD_NEW required:
      customer, initial_price, exact OKPD, procurement start/end,
      region, source_origin; delivery_* only if source has them.
    winner / final_contract_price / award_at are NOT required on OPEN
    (NULL is correct for a new procurement).

    AWARDED required where source provides:
      customer, winner/contractor, initial_price, final_contract_price,
      award date, execution dates, exact OKPD, region.
    """
    src = source_row or {}
    lc = str(model_input.get("normalized_lifecycle") or "").upper()
    is_open = lc == "OPEN"
    is_awarded = lc == "AWARDED"
    codes = model_input.get("okpd_codes") or []

    def _has(obj: Dict[str, Any], *keys: str) -> bool:
        for k in keys:
            v = obj.get(k)
            if v is not None and str(v).strip() not in ("", "None"):
                return True
        return False

    missing = {
        "MODEL_INPUT_WITHOUT_EXACT_OKPD": 0 if codes else 1,
        "MODEL_INPUT_WITHOUT_REGION": 0 if model_input.get("primary_commercial_region") else 1,
        "MODEL_INPUT_WITHOUT_CUSTOMER": 0 if model_input.get("customer_name") else 1,
        "MODEL_INPUT_WITHOUT_INITIAL_PRICE": 0 if _has(model_input, "initial_price") else 1,
        "MODEL_INPUT_WITHOUT_SOURCE_ORIGIN": 0 if _has(model_input, "source_origin") else 1,
        # OPEN-only procedure dates
        "MODEL_INPUT_WITHOUT_PROCUREMENT_START_ACTIVE": (
            0
            if (
                not is_open
                or _has(model_input, "procurement_start_at", "source_start_date")
            )
            else 1
        ),
        "MODEL_INPUT_WITHOUT_PROCUREMENT_END_ACTIVE": (
            0
            if (
                not is_open
                or _has(model_input, "procurement_end_at", "source_end_date")
            )
            else 1
        ),
        # delivery dates required on OPEN only when source has them
        "MODEL_INPUT_WITHOUT_DELIVERY_START_WHEN_SOURCE_HAS": (
            0
            if (
                not is_open
                or not _has(src, "delivery_start_date", "source_delivery_start_date")
                or _has(model_input, "delivery_start_at", "source_delivery_start_date")
            )
            else 1
        ),
        "MODEL_INPUT_WITHOUT_DELIVERY_END_WHEN_SOURCE_HAS": (
            0
            if (
                not is_open
                or not _has(src, "delivery_end_date", "source_delivery_end_date")
                or _has(model_input, "delivery_end_at", "source_delivery_end_date")
            )
            else 1
        ),
        # AWARDED-only — never required on OPEN
        "MODEL_INPUT_WITHOUT_WINNER_AWARDED": (
            0
            if (
                not is_awarded
                or not _has(src, "winner_name", "contractor_name", "winner")
                or _has(model_input, "winner_name")
            )
            else 1
        ),
        "MODEL_INPUT_WITHOUT_FINAL_PRICE_AWARDED": (
            0
            if (
                not is_awarded
                or not _has(src, "final_price", "final_contract_price")
                or _has(model_input, "final_contract_price")
            )
            else 1
        ),
        "MODEL_INPUT_WITHOUT_AWARD_DATE_AWARDED": (
            0
            if (
                not is_awarded
                or not _has(src, "award_date", "award_at", "contract_signed_at")
                or _has(model_input, "award_at")
            )
            else 1
        ),
        "MODEL_INPUT_WITHOUT_EXECUTION_END_AWARDED": (
            0
            if (
                not is_awarded
                or not _has(
                    src,
                    "delivery_end_date",
                    "execution_end_at",
                    "contract_execution_end_at",
                    "end_date",
                )
                or _has(
                    model_input,
                    "contract_execution_end_at",
                    "delivery_end_at",
                    "source_delivery_end_date",
                )
            )
            else 1
        ),
        # Explicit non-requirements on OPEN (document correctness)
        "OPEN_WINNER_NULL_OK": 1 if (is_open and not _has(model_input, "winner_name")) else 0,
        "OPEN_FINAL_PRICE_NULL_OK": (
            1 if (is_open and not _has(model_input, "final_contract_price")) else 0
        ),
        "PROCUREMENT_DELIVERY_DATE_CONFLATION": 0,
    }
    return missing
