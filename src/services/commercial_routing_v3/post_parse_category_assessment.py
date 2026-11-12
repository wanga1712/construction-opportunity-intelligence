"""Post-parse commercial assessment for categories supported by saved estimate rows.

This stage is deliberately separate from the initial procurement assessment:
it cannot alter the procurement-level medal, and it never treats object
context as proof that a category is present.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

PROMPT_VERSION = "post_parse_category_assessment_v4"
ALLOWED_TRACKS = {
    "DIRECT_SUPPLY",
    "EMBEDDED_MATERIAL",
    "DESIGN_REQUIREMENT",
    "DESIGN_INFLUENCE",
    "UNKNOWN",
}
ALLOWED_RELATIONS = {
    "PRIMARY_SUBJECT",
    "EMBEDDED_IN_WORKS",
    "SPECIFIED_IN_PROJECT",
    "EQUIPMENT_WITH_INSTALLATION",
    "CONSUMABLE_FOR_SERVICE",
    "INCIDENTAL",
    "UNKNOWN",
}
ALLOWED_STATES = {"COMMERCIALLY_SIGNIFICANT", "INCIDENTAL", "REVIEW_REQUIRED"}


def _verified_line_total(row: dict[str, Any]) -> bool:
    """Only source-mapped, arithmetically coherent rows may fund a category."""
    if str(row.get("layout_status") or "").upper() != "CONSISTENT":
        return False
    try:
        quantity = Decimal(str(row["quantity_value"]))
        unit_price = Decimal(str(row["unit_price_value"]))
        total = Decimal(str(row["total_value"]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return False
    if quantity <= 0 or unit_price <= 0 or total <= 0:
        return False
    tolerance = max(Decimal("2"), total * Decimal("0.01"))
    return abs(quantity * unit_price - total) <= tolerance


def _supply_value_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate copied source positions without collapsing distinct rows."""
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        name = str(
            row.get("name_normalized") or row.get("name_raw") or ""
        ).strip().casefold()
        quantity = row.get("quantity_value")
        unit = str(
            row.get("unit_normalized") or row.get("unit_raw") or ""
        ).strip().upper()
        total = row.get("total_value")
        row_ref = str(row.get("row_ref") or "").strip().casefold()
        quote = " ".join(str(row.get("source_quote") or "").split())
        key = (name, quantity, unit, total, row_ref, quote)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _verified_supply_volume(row: dict[str, Any]) -> bool:
    """Explicit quantity/unit/line-total may fund supply-volume scoring."""
    if not str(row.get("source_quote") or "").strip():
        return False
    try:
        quantity = Decimal(str(row["quantity_value"]))
        total = Decimal(str(row["total_value"]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return False
    unit = str(
        row.get("unit_normalized") or row.get("unit_raw") or ""
    ).strip()
    return quantity > 0 and total > 0 and bool(unit)


def _compact_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        result.append(
            {
                "row_id": row.get("row_id"),
                "source_document_id": row.get("source_document_id"),
                "row_ref": row.get("row_ref"),
                "row_kind": row.get("row_kind"),
                "name": str(row.get("name_raw") or "")[:400],
                "source_quote": str(row.get("source_quote") or "")[:900],
                "quantity": row.get("quantity_value"),
                "unit": row.get("unit_normalized") or row.get("unit_raw"),
                "unit_price": row.get("unit_price_value"),
                "line_total": row.get("total_value"),
                "technical_attributes": row.get("technical_attributes") or [],
            }
        )
    return result


def build_prompt(
    procurements: Iterable[dict[str, Any]], *, max_rows_per_category: int = 40
) -> str:
    """Build one model request for a procurement batch (normally 20 cards)."""
    payload = []
    for procurement in procurements:
        categories = []
        for category in procurement.get("categories") or []:
            rows = list(category.get("rows") or [])[:max_rows_per_category]
            categories.append(
                {
                    "category_code": category.get("category_code"),
                    "subcategory_code": category.get("subcategory_code"),
                    "full_category_row_count": (
                        int(category.get("row_count_total") or len(rows))
                        if category.get("evidence_scope") == "FULL_CATEGORY_ROWS"
                        else None
                    ),
                    "rows_in_supplied_evidence": len(rows),
                    "evidence_scope": category.get("evidence_scope") or "UNVERIFIED",
                    "source_value_coverage": category.get("source_value_coverage"),
                    "evidence_rows": _compact_rows(rows),
                }
            )
        payload.append(
            {
                "procurement_id": procurement.get("procurement_id"),
                "title": procurement.get("title"),
                "lifecycle": procurement.get("lifecycle"),
                "source_table": procurement.get("source_table"),
                "initial_route_profile": procurement.get("initial_route_profile"),
                "initial_procurement_form": procurement.get("initial_procurement_form"),
                "initial_analysis_mode": procurement.get("initial_analysis_mode"),
                "initial_assessment_status": procurement.get("initial_assessment_status"),
                "initial_assessment_confidence": procurement.get("initial_assessment_confidence"),
                "procurement_mode": procurement.get("procurement_mode"),
                "object_applicable": procurement.get("object_applicable"),
                "object_sector": procurement.get("object_sector"),
                "object_type": procurement.get("object_type"),
                "classification_status": procurement.get("classification_status"),
                "resolved_opportunity_track": _resolve_initial_track(procurement)["track"],
                "track_resolution_source": _resolve_initial_track(procurement)["source"],
                "categories": categories,
            }
        )
    return (
        "Rows are preclassified estimate evidence (goods or explicitly scoped "
        "structural reinforcement work); their category presence is "
        "settled. Return one routing result for every supplied category. A "
        "single valid category evidence row is sufficient; never downgrade because the evidence "
        "is sampled or contains one row. Set COMMERCIALLY_SIGNIFICANT unless "
        "every cited row is clearly an accessory/support item from another "
        "product family; use REVIEW_REQUIRED only if that distinction is unclear.\n"
        "The saved initial route/form and canonical object fields were assigned "
        "before document download. resolved_opportunity_track is the "
        "authoritative result derived from that hierarchy. Copy it exactly; "
        "never infer or reclassify DIRECT vs OBJECT/PROJECT from title or rows. "
        "UNKNOWN means initial hierarchy was missing or conflicting.\n"
        "Relation: embedded estimate product => EMBEDDED_IN_WORKS; direct goods "
        "contract => PRIMARY_SUBJECT; otherwise UNKNOWN. Do not infer social, "
        "commercial, road, or street object classes; retain unknown hierarchy. "
        "Do not calculate a category price or medal. Use exact supplied row IDs. "
        "Do not return confidence; it comes from validated row decisions. Return "
        "only the requested JSON object; no technical attributes or product "
        "normalization. Return JSON only: "
        "{\"assessments\":[{\"procurement_id\":1,"
        "\"categories\":[{\"category_code\":\"...\","
        "\"subcategory_code\":\"...\","
        "\"commercial_state\":\"COMMERCIALLY_SIGNIFICANT|INCIDENTAL|REVIEW_REQUIRED\","
        "\"opportunity_track\":\"DIRECT_SUPPLY|EMBEDDED_MATERIAL|DESIGN_REQUIREMENT|DESIGN_INFLUENCE|UNKNOWN\","
        "\"product_relation\":\"PRIMARY_SUBJECT|EMBEDDED_IN_WORKS|SPECIFIED_IN_PROJECT|EQUIPMENT_WITH_INSTALLATION|CONSUMABLE_FOR_SERVICE|INCIDENTAL|UNKNOWN\","
        "\"evidence_row_ids\":[1],\"reason\":\"...\"}]}]}\n"
        "Input (evidence_scope identifies full vs sampled rows):\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
    )


def validate_response(
    raw: str, procurements: Iterable[dict[str, Any]]
) -> dict[int, list[dict[str, Any]]]:
    """Validate model output against the exact supplied category and row IDs."""
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        decoded = {}
    input_map: dict[int, dict[tuple[str, str], dict[str, Any]]] = {}
    hierarchy_by_pid: dict[int, dict[str, str]] = {}
    for procurement in procurements:
        pid = int(procurement["procurement_id"])
        hierarchy_by_pid[pid] = _resolve_initial_track(procurement)
        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for category in procurement.get("categories") or []:
            key = (str(category.get("category_code") or ""), str(category.get("subcategory_code") or ""))
            pairs[key] = {
                "rows_by_id": {
                    int(r["row_id"]): r
                    for r in category.get("rows") or []
                    if r.get("row_id") is not None
                },
                "evidence_scope": str(category.get("evidence_scope") or "UNVERIFIED"),
            }
        input_map[pid] = pairs
    output: dict[int, list[dict[str, Any]]] = {pid: [] for pid in input_map}
    assessments = decoded.get("assessments", []) if isinstance(decoded, dict) else []
    for item in assessments if isinstance(assessments, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("procurement_id"))
        except (TypeError, ValueError):
            continue
        if pid not in input_map:
            continue
        categories = item.get("categories")
        if not isinstance(categories, list):
            continue
        seen: set[tuple[str, str]] = set()
        for decision in categories:
            if not isinstance(decision, dict):
                continue
            key = (str(decision.get("category_code") or ""), str(decision.get("subcategory_code") or ""))
            category_input = input_map[pid].get(key)
            if category_input is None or key in seen:
                continue
            rows_by_id = category_input["rows_by_id"]
            seen.add(key)
            evidence_ids = decision.get("evidence_row_ids")
            valid_ids = sorted({int(x) for x in evidence_ids if str(x).isdigit()} & rows_by_id.keys()) if isinstance(evidence_ids, list) else []
            confidence_values = []
            for row_id in valid_ids:
                try:
                    confidence_values.append(float(rows_by_id[row_id].get("row_confidence") or 0))
                except (TypeError, ValueError):
                    confidence_values.append(0.0)
            confidence = min(confidence_values) if confidence_values else 0.0
            state = str(decision.get("commercial_state") or "REVIEW_REQUIRED").upper()
            model_track = str(decision.get("opportunity_track") or "UNKNOWN").upper()
            if model_track not in ALLOWED_TRACKS:
                model_track = "UNKNOWN"
            track = hierarchy_by_pid[pid]["track"]
            relation = str(decision.get("product_relation") or "UNKNOWN").upper()
            if state not in ALLOWED_STATES:
                state = "REVIEW_REQUIRED"
            if relation not in ALLOWED_RELATIONS:
                relation = "UNKNOWN"
            if not valid_ids or confidence < 0.65:
                state = "REVIEW_REQUIRED"
            missing_information = []
            cited_rows = [rows_by_id[row_id] for row_id in valid_ids]
            for field, aliases in {
                "quantity": ("quantity_value", "quantity"),
                "unit": ("unit_normalized", "unit_raw", "unit"),
                "unit_price": ("unit_price_value", "unit_price"),
                "line_total": ("total_value", "total"),
            }.items():
                absent = sum(
                    not any(row.get(alias) is not None and row.get(alias) != "" for alias in aliases)
                    for row in cited_rows
                )
                if absent:
                    missing_information.append(f"{field}:{absent}/{len(cited_rows)}")
            output[pid].append(
                {
                    "category_code": key[0],
                    "subcategory_code": key[1] or None,
                    "commercial_state": state,
                    "opportunity_track": track,
                    "model_opportunity_track": model_track,
                    "track_resolution_source": hierarchy_by_pid[pid]["source"],
                    "product_relation": relation,
                    "evidence_row_ids": valid_ids,
                    "evidence_scope": category_input["evidence_scope"],
                    "missing_information": missing_information,
                    "confidence": confidence,
                    "reason": str(decision.get("reason") or "")[:800],
                    "prompt_version": PROMPT_VERSION,
                }
            )
        # Missing outputs are explicit review items; never silently project them.
        returned = { (x["category_code"], x["subcategory_code"] or "") for x in output[pid] }
        for key in input_map[pid]:
            if key not in returned:
                output[pid].append(
                    {
                        "category_code": key[0], "subcategory_code": key[1] or None,
                        "commercial_state": "REVIEW_REQUIRED", "opportunity_track": "UNKNOWN",
                        "model_opportunity_track": "UNKNOWN",
                        "track_resolution_source": "NO_MODEL_RESULT",
                        "product_relation": "UNKNOWN", "evidence_row_ids": [],
                        "evidence_scope": input_map[pid][key]["evidence_scope"],
                        "missing_information": ["model_omitted"],
                        "confidence": 0.0, "reason": "model_omitted_category",
                        "prompt_version": PROMPT_VERSION,
                    }
                )
    return output


def _resolve_initial_track(procurement: dict[str, Any]) -> dict[str, str]:
    """Resolve track from the saved pre-download hierarchy; never infer from title."""
    assessment_ok = (
        str(procurement.get("initial_assessment_status") or "").upper() == "SUCCESS"
    )
    try:
        assessment_ok = assessment_ok and float(
            procurement.get("initial_assessment_confidence") or 0
        ) >= 0.65
    except (TypeError, ValueError):
        assessment_ok = False

    form = str(procurement.get("initial_procurement_form") or "UNKNOWN").upper()
    analysis = str(procurement.get("initial_analysis_mode") or "UNKNOWN").upper()
    route = str(procurement.get("initial_route_profile") or "UNKNOWN").upper()
    if not assessment_ok:
        form = analysis = route = "UNKNOWN"

    object_resolved = str(procurement.get("classification_status") or "").upper() in {
        "RESOLVED_REVIEWED", "RESOLVED_HIGH_CONFIDENCE", "RESOLVED_MODEL"
    }
    mode = str(procurement.get("procurement_mode") or "UNKNOWN").upper()
    object_applicable = procurement.get("object_applicable") if object_resolved else None

    form_tracks = {
        "DIRECT_GOODS_PURCHASE": "DIRECT_SUPPLY",
        "CONSTRUCTION_WORKS": "EMBEDDED_MATERIAL",
        "DESIGN_AND_BUILD": "EMBEDDED_MATERIAL",
        "DESIGN_EXPERTISE_AND_BUILD": "EMBEDDED_MATERIAL",
        "WORKS_OTHER": "EMBEDDED_MATERIAL",
        "DESIGN_ONLY": "DESIGN_REQUIREMENT",
        "SURVEY_AND_DESIGN": "DESIGN_REQUIREMENT",
    }
    direct_signals = set()
    embedded_signals = set()
    design_signals = set()
    if form in form_tracks:
        value = form_tracks[form]
        {"DIRECT_SUPPLY": direct_signals, "EMBEDDED_MATERIAL": embedded_signals,
         "DESIGN_REQUIREMENT": design_signals}[value].add("initial_procurement_form")
    if analysis == "DIRECT_PRODUCT":
        direct_signals.add("initial_analysis_mode")
    elif analysis == "EMBEDDED_MATERIAL_DISCOVERY":
        embedded_signals.add("initial_analysis_mode")
    elif analysis == "FUTURE_REQUIREMENT_DISCOVERY":
        design_signals.add("initial_analysis_mode")
    if mode in {"DIRECT", "DIRECT_SUPPLY"} or object_applicable is False:
        direct_signals.add("canonical_object_hierarchy")
    elif mode in {"OBJECT", "OBJECT_PROJECT"} or object_applicable is True:
        embedded_signals.add("canonical_object_hierarchy")
    scope_type = str(procurement.get("procurement_scope_type") or "").upper()
    scope_track = {
        "DIRECT_GOODS": "DIRECT_SUPPLY",
        "WORKS_WITH_EMBEDDED_PRODUCTS": "EMBEDDED_MATERIAL",
        "DESIGN_PROJECT": "DESIGN_REQUIREMENT",
    }.get(scope_type)
    if scope_track:
        {
            "DIRECT_SUPPLY": direct_signals,
            "EMBEDDED_MATERIAL": embedded_signals,
            "DESIGN_REQUIREMENT": design_signals,
        }[scope_track].add("procurement_scope_authority")

    strong_tracks = sum(bool(signals) for signals in (direct_signals, embedded_signals, design_signals))
    if strong_tracks > 1:
        return {"track": "UNKNOWN", "source": "INITIAL_HIERARCHY_CONFLICT"}
    if direct_signals:
        return {"track": "DIRECT_SUPPLY", "source": "+".join(sorted(direct_signals))}
    if embedded_signals:
        return {"track": "EMBEDDED_MATERIAL", "source": "+".join(sorted(embedded_signals))}
    if design_signals:
        return {"track": "DESIGN_REQUIREMENT", "source": "+".join(sorted(design_signals))}

    # Route profile is a coarse fallback only; it never overrides a specific
    # procurement form or a resolved canonical object-mode decision.
    if route == "DIRECT_SUPPLY":
        return {"track": "DIRECT_SUPPLY", "source": "initial_route_profile"}
    if route in {"CONSTRUCTION_BUILDING", "CONSTRUCTION_INFRASTRUCTURE"}:
        return {"track": "EMBEDDED_MATERIAL", "source": "initial_route_profile"}
    if route == "DESIGN_ENGINEERING":
        return {"track": "DESIGN_REQUIREMENT", "source": "initial_route_profile"}
    return {"track": "UNKNOWN", "source": "INITIAL_HIERARCHY_MISSING"}


def score_category_decisions(
    procurement: dict[str, Any],
    normalized_result: dict[str, Any],
    decisions: list[dict[str, Any]],
    rows_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create scored category-opportunity payloads for existing persistence.

    The caller supplies the existing V3 card context. This function only emits
    evidence-backed category opportunities; it never updates card-level medal
    fields. Line totals are exposed as a category value only when every cited
    row has a parsed total.
    """
    from src.services.commercial_routing_v3.candidate_scoring import (
        apply_candidate_scoring_to_hypotheses,
    )

    hypotheses: list[dict[str, Any]] = []
    for decision in decisions:
        if decision.get("commercial_state") != "COMMERCIALLY_SIGNIFICANT":
            continue
        row_ids = [int(value) for value in decision.get("evidence_row_ids") or []]
        evidence_rows = [rows_by_id[row_id] for row_id in row_ids if row_id in rows_by_id]
        if not evidence_rows:
            continue
        category_rows = [
            row for row in rows_by_id.values()
            if str(row.get("category_code") or "") == str(decision.get("category_code") or "")
            and str(row.get("subcategory_code") or "")
            == str(decision.get("subcategory_code") or "")
        ]
        value_rows = (
            category_rows
            if decision.get("evidence_scope") == "FULL_CATEGORY_ROWS"
            else evidence_rows
        )
        value_rows = _supply_value_rows(value_rows)
        totals = [row.get("total_value") for row in value_rows]
        has_complete_value = (
            decision.get("evidence_scope") == "FULL_CATEGORY_ROWS"
            and bool(value_rows)
            and all(_verified_supply_volume(row) for row in value_rows)
        )
        total_value = sum(float(value) for value in totals) if has_complete_value else None
        line_total_count = sum(
            _verified_supply_volume(row) for row in value_rows
        )
        quartet_count = sum(_verified_line_total(row) for row in value_rows)
        confidence = float(decision.get("confidence") or 0.0)
        positive_evidence = [
            {
                "source": "STRUCTURED_ESTIMATE_ROW",
                "row_id": int(row["row_id"]),
                "source_document_id": row.get("source_document_id"),
                "row_ref": row.get("row_ref"),
                "name": str(row.get("name_raw") or "")[:400],
                "row_kind": row.get("row_kind"),
                "source_quote": str(row.get("source_quote") or "")[:900],
                "quantity": row.get("quantity_value"),
                "unit": row.get("unit_normalized") or row.get("unit_raw"),
                "unit_price": row.get("unit_price_value"),
                "line_total": row.get("total_value"),
                "layout_status": row.get("layout_status"),
            }
            for row in value_rows
        ]
        positive_evidence.append(
            {
                "source": "ESTIMATE_CATEGORY_COVERAGE",
                "evidence_scope": decision.get("evidence_scope") or "UNVERIFIED",
                "missing_information": decision.get("missing_information") or [],
                "row_count": len(value_rows),
            }
        )
        hypotheses.append(
            {
                "category_code": decision["category_code"],
                "subcategory_code": decision.get("subcategory_code"),
                "opportunity_track": decision.get("opportunity_track") or "UNKNOWN",
                "evidence_role": "DIRECT_CATEGORY_EVIDENCE",
                "confirmation_required": False,
                "confidence": confidence,
                "expected_category_value": total_value,
                "category_value_basis": (
                    "EXPLICIT_LINE_TOTAL_SUPPLY_VOLUME"
                    if has_complete_value
                    else "UNKNOWN_ADDRESSABLE_VALUE"
                ),
                "category_value_coverage": {
                    "rows_cited": len(evidence_rows),
                    "rows_in_category_scope": len(value_rows),
                    "rows_with_total": line_total_count,
                    "rows_with_verified_quartet": quartet_count,
                    "total_is_complete": has_complete_value,
                },
                "product_relation": decision.get("product_relation") or "UNKNOWN",
                "positive_evidence": positive_evidence,
                "reason_codes": ["POST_PARSE_ESTIMATE_EVIDENCE", decision.get("commercial_state")],
                "reason": decision.get("reason") or "",
            }
        )
    scored: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        # The whole-procurement NMCK must not inflate a category medal. The
        # scorer receives only a fully evidenced category subtotal; otherwise
        # its scale/value inputs are zero and the direct-value guard fails low.
        category_procurement = dict(procurement)
        category_value = hypothesis.get("expected_category_value")
        category_procurement["price"] = category_value or 0
        model_input = dict(procurement.get("v3_model_input") or {})
        model_input["initial_price"] = category_value or 0
        model_input["final_contract_price"] = None
        category_procurement["v3_model_input"] = model_input
        scored.extend(
            apply_candidate_scoring_to_hypotheses(
                [hypothesis],
                procurement=category_procurement,
                normalized=normalized_result,
                apply_category_admission=False,
                medal_scope="PROCUREMENT_CATEGORY",
                medal_assignment_stage="POST_PARSE",
            )
        )
    for item in scored:
        item["commercial_category_code"] = item.get("category_code")
        item["commercial_subcategory_code"] = item.get("subcategory_code")
        item["category_confidence"] = item.get("confidence")
        item["research_priority"] = item.get("commercial_priority_score") or 0
        item["research_action"] = (
            "DEEP_RESEARCH" if item.get("candidate_medal") in {"GOLD", "SILVER"}
            else "LIGHT_RESEARCH" if item.get("candidate_medal") == "BRONZE"
            else "METADATA_ONLY"
        )
        item["candidate_initial_score"] = item.get("final_score")
        item["candidate_initial_medal"] = item.get("candidate_medal")
        item["candidate_initial_scoring_version"] = item.get("candidate_scoring_version")
        item["current_effective_score"] = item.get("final_score")
        item["current_effective_medal"] = item.get("candidate_medal")
        item["current_effective_reason"] = "POST_PARSE_ESTIMATE_EVIDENCE"
        item["semantic_hypothesis"] = {
            "category_code": item.get("category_code"),
            "subcategory_code": item.get("subcategory_code"),
            "opportunity_track": item.get("opportunity_track"),
            "product_relation": item.get("product_relation"),
            "evidence_role": item.get("evidence_role"),
            "confidence": item.get("confidence"),
            "medal_scope": "PROCUREMENT_CATEGORY",
            "medal_assignment_stage": "POST_PARSE",
            "stage_end_date": item.get("stage_end_date"),
            "stage_end_source": item.get("stage_end_source"),
        }
    normalized_result.update(
        {
            "routing_version": "post_parse_rows_v1",
            "prompt_version": PROMPT_VERSION,
            "model_name": normalized_result.get("model_name"),
            "category_opportunities": scored,
        }
    )
    return scored
