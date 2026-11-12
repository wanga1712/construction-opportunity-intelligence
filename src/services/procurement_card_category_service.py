"""PROCUREMENT_CARD_CATEGORY_PIPELINE_V1 — read-model вкладки «Категории».

Один блок = одна commercial category opportunity. Бизнес-логику здесь не
считаем: медали берём как есть из authority-полей opportunity, товары — из
GOOD_SUPPLY_FACTS_V1, статус модели — из validation_status/validated_at,
статус документов — из document_extraction_outcomes + очереди.

Read-only. Ничего не пишет в CRM/DI и не трогает scoring/medal/queue.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional, Tuple


TRUST_GROUPS = {
    "TRUSTED_PRODUCTION": "ПОДТВЕРЖДЕНО",
    "SECTION_CONFIRMED": "ПОДТВЕРЖДЕНО РАЗДЕЛОМ",
    "MANUAL_PROOF_QUARANTINE": "ОЖИДАЕТ ПРОВЕРКИ",
    "DEV_EXPOSED": "ТЕХНИЧЕСКИЙ КАНДИДАТ",
    "QUALITY_REJECTED": "ОТКЛОНЕНО КАЧЕСТВОМ",
}

_PENDING_VALIDATION = ("UNKNOWN", "RAW", "PENDING")
_UNCLASSIFIED_SENTINEL = "SUBCATEGORY_NOT_ASSIGNED"
_EMBEDDED_TRACK = "EMBEDDED_MATERIAL"
COMPOSITE_CARD_SOURCES = {
    ("composite_structures", "pultruded_composite_profiles"),
    ("composite_structures", "frp_gratings"),
    ("composite_structures", "composite_guardrails_stairs"),
    ("composite_structures", "composite_trays"),
    ("composite_structures", "composite_drainage_channels"),
    ("structural_reinforcement", "composite_rebar"),
    ("structural_reinforcement", "composite_fiber"),
    ("structural_reinforcement", "external_carbon_reinforcement"),
}


def _di_conn():
    import psycopg2

    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kw = dict(require_crm_db_connect_kwargs())
    kw["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    kw.setdefault("connect_timeout", 8)
    return psycopg2.connect(**kw)


def load_model_validation_counts(
    procurement_id: int, *, conn: Any = None
) -> Dict[str, Dict[str, Any]]:
    """Счётчики validator по категориям. UNKNOWN терминален только с validated_at."""
    own = conn is None
    db = conn or _di_conn()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT d.category_code,
                       count(*) FILTER (
                           WHERE upper(coalesce(d.validation_status,'')) IN ('UNKNOWN','RAW','PENDING')
                             AND d.validated_at IS NULL
                       ) AS pending,
                       count(*) FILTER (
                           WHERE upper(coalesce(d.validation_status,'')) = 'CONFIRMED'
                       ) AS confirmed,
                       count(*) FILTER (
                           WHERE upper(coalesce(d.validation_status,'')) = 'REJECTED'
                       ) AS rejected,
                       count(*) FILTER (
                           WHERE upper(coalesce(d.validation_status,'')) = 'UNKNOWN'
                             AND d.validated_at IS NOT NULL
                       ) AS unknown,
                       max(d.validated_at) FILTER (
                           WHERE d.validated_at IS NOT NULL
                       ) AS completed_at
                  FROM document_match_details d
                  JOIN document_matches m ON m.id = d.match_id
                 WHERE m.procurement_id = %s
                 GROUP BY d.category_code
                """,
                (int(procurement_id),),
            )
            return {
                str(cat or "unknown"): {
                    "pending": int(p or 0),
                    "confirmed": int(c or 0),
                    "rejected": int(r or 0),
                    "unknown": int(u or 0),
                    "completed_at": done,
                }
                for cat, p, c, r, u, done in cur.fetchall()
            }
    finally:
        if own:
            db.close()


def load_extraction_outcomes(
    procurement_id: int, *, conn: Any = None
) -> Dict[str, Dict[str, Any]]:
    """Последний extraction outcome по категории (FACTS_FOUND / NO_FACTS)."""
    own = conn is None
    db = conn or _di_conn()
    try:
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (category_code)
                       category_code, outcome, facts_found, updated_at
                  FROM document_extraction_outcomes
                 WHERE procurement_id = %s
                 ORDER BY category_code, updated_at DESC NULLS LAST, id DESC
                """,
                (int(procurement_id),),
            )
            return {
                str(cat): {
                    "outcome": outcome,
                    "facts_found": int(facts or 0),
                    "updated_at": updated,
                }
                for cat, outcome, facts, updated in cur.fetchall()
            }
    finally:
        if own:
            db.close()


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _document_stage(
    queue_status: Any,
    outcome: Optional[Dict[str, Any]],
) -> str:
    from src.services.document_queue_progress_service import queue_status_label

    if outcome and outcome.get("outcome") == "FACTS_FOUND":
        return "документы обработаны · факты найдены"
    if outcome and outcome.get("outcome") == "NO_FACTS":
        return "документы обработаны · фактов нет"
    return queue_status_label(queue_status)


def _model_stage(counts: Optional[Dict[str, Any]]) -> str:
    if not counts:
        return "нет данных"
    pending = int(counts.get("pending") or 0)
    confirmed = int(counts.get("confirmed") or 0)
    rejected = int(counts.get("rejected") or 0)
    if pending > 0:
        return "ожидает проверки"
    if confirmed or rejected:
        return "завершена"
    return "нет подтверждённых кандидатов"


def _quantities_by_unit(products: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for p in products:
        qty = _number(p.get("quantity"))
        unit = str(p.get("unit") or "").strip()
        if qty is None or not unit:
            continue
        out[unit] = round(out.get(unit, 0.0) + qty, 6)
    return out


def _products_for_category(
    supply_facts: Iterable[Dict[str, Any]], category_code: str
) -> List[Dict[str, Any]]:
    return [
        f for f in supply_facts
        if str(f.get("category_code") or "") == category_code
    ]


def _is_composite_drainage_material(fact: Dict[str, Any]) -> bool:
    name = str(
        fact.get("material")
        or fact.get("product_name_normalized")
        or fact.get("product_name_raw")
        or ""
    ).lower()
    if "compomax" in name:
        return True
    has_composite = "композит" in name or "полимербетон" in name
    has_drainage = "водоотвод" in name or "лоток" in name
    return has_composite and has_drainage


def _products_for_opportunity(
    supply_facts: Iterable[Dict[str, Any]],
    *,
    category_code: str,
    subcategory_code: str,
) -> List[Dict[str, Any]]:
    selected_subcategory = (
        subcategory_code
        if subcategory_code and subcategory_code != _UNCLASSIFIED_SENTINEL
        else None
    )
    products = _products_for_category(supply_facts, category_code)
    if selected_subcategory:
        products = [
            product
            for product in products
            if str(product.get("subcategory_code") or "") == selected_subcategory
        ]
    return products


def _factual_product_subcategory(
    product: Dict[str, Any],
    *,
    category_code: str,
    opportunity_subcategory: str,
) -> Optional[str]:
    source_category = str(product.get("category_code") or "").strip()
    source_subcategory = str(product.get("subcategory_code") or "").strip()
    if not source_subcategory:
        return None
    selected = (
        opportunity_subcategory
        if opportunity_subcategory
        and opportunity_subcategory != _UNCLASSIFIED_SENTINEL
        else None
    )
    if source_category != category_code and selected:
        return selected
    return source_subcategory


def _factual_product_groups(
    products: Iterable[Dict[str, Any]],
    *,
    category_code: str,
    opportunity_subcategory: str,
) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for product in products:
        subcategory = _factual_product_subcategory(
            product,
            category_code=category_code,
            opportunity_subcategory=opportunity_subcategory,
        )
        if subcategory:
            groups.setdefault(subcategory, []).append(product)
    return groups


def _position_subcategory_summary(positions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, int] = {}
    for position in positions or ():
        code = str(position.get("subcategory_code") or "").strip()
        if code:
            grouped[code] = grouped.get(code, 0) + 1
    return [
        {"subcategory_code": code, "position_count": count}
        for code, count in sorted(grouped.items())
    ]


def build_category_cards(
    *,
    opportunities: Iterable[Dict[str, Any]],
    supply_facts: Iterable[Dict[str, Any]],
    documents: Iterable[Dict[str, Any]],
    queue_progress: Dict[str, Any],
    procurement_id: int,
    model_counts: Dict[str, Dict[str, Any]],
    extraction_outcomes: Dict[str, Dict[str, Any]],
    evidence_rows: Iterable[Dict[str, Any]] = (),
    category_positions: Optional[Iterable[Dict[str, Any]]] = None,
    procurement_title: Any = None,
    okpd_name: Any = None,
    object_class: Any = None,
) -> List[Dict[str, Any]]:
    """Собрать карточки категорий (одна opportunity = один блок)."""
    from src.services.document_queue_progress_service import queue_eta_seconds
    from src.services.object_section_match_service import compare_section_to_procurement

    facts = list(supply_facts or [])
    positions_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for position in category_positions or ():
        code = str(position.get("category_code") or "").strip()
        if code:
            positions_by_category.setdefault(code, []).append(dict(position))
    evidence = list(evidence_rows or [])
    docs = list(documents or [])
    latest = (queue_progress.get("latest") or {}).get(int(procurement_id))
    queue_status = latest[0] if latest else None
    done_docs = sum(
        1 for d in docs
        if str(d.get("download_status") or "").upper() == "COMPLETED"
    )
    eta = queue_eta_seconds(queue_progress, int(procurement_id))
    total_docs = len(docs)

    cards: List[Dict[str, Any]] = []
    seen: set = set()
    for opp in opportunities or []:
        code = str(opp.get("commercial_category_code") or "").strip()
        if not code:
            continue
        sub = str(opp.get("commercial_subcategory_code") or "").strip()
        track = str(opp.get("opportunity_track") or "").strip()
        key = (code, sub, track)
        if key in seen:
            continue
        seen.add(key)

        products = _products_for_opportunity(
            facts,
            category_code=code,
            subcategory_code=sub,
        )
        if category_positions is not None:
            positions = [
                row for row in positions_by_category.get(code, [])
                if not sub or sub == _UNCLASSIFIED_SENTINEL
                or str(row.get("subcategory_code") or "") == sub
            ]
            value_ids = {
                str(row.get("structured_entity_id") or row.get("id") or "")
                for row in products
            }
            confirmed_states = {"TRUSTED_PRODUCTION", "SECTION_CONFIRMED"}
            for position in positions:
                position["value_eligible"] = str(
                    position.get("structured_entity_id") or ""
                ) in value_ids
                position["confirmation_eligible"] = (
                    str(position.get("trust_state") or "").upper()
                    in confirmed_states
                )
            category_value = _number(opp.get("expected_category_value"))
            card = {
                "category_code": code,
                "category_name": opp.get("category_name") or code,
                "subcategory_code": sub or None,
                "subcategory_name": opp.get("subcategory_name") or sub or None,
                "track": track or None,
                "status": opp.get("status"),
                "candidate_initial_score": _number(opp.get("candidate_initial_score")),
                "candidate_initial_medal": opp.get("candidate_initial_medal"),
                "confirmed_base_score": _number(opp.get("confirmed_base_score")),
                "confirmed_base_medal": opp.get("confirmed_base_medal"),
                "current_effective_score": _number(opp.get("current_effective_score")),
                "current_effective_medal": opp.get("current_effective_medal"),
                "current_effective_reason": opp.get("current_effective_reason"),
                "commercial_state": opp.get("commercial_state"),
                "confirmation_state": (
                    "CONFIRMED" if opp.get("confirmed_base_medal") else "UNCONFIRMED"
                ),
                "positions": positions,
                "products": positions,
                "position_count": len(positions),
                "line_count": len(positions),
                "source_row_count": len(positions),
                "value_positions": [p for p in positions if p["value_eligible"]],
                "value_position_count": sum(1 for p in positions if p["value_eligible"]),
                "confirmed_positions": [p for p in positions if p["confirmation_eligible"]],
                "confirmed_position_count": sum(1 for p in positions if p["confirmation_eligible"]),
                "commercial_value": category_value,
                "commercial_value_basis": opp.get("category_value_basis"),
                "material_value": category_value,
                "document_stage": _document_stage(queue_status, extraction_outcomes.get(code)),
                "document_progress": {"done": done_docs, "total": total_docs, "scope": "procurement"},
                "document_eta_seconds": eta,
                "model_stage": _model_stage(model_counts.get(code)),
                "model_pending": (model_counts.get(code) or {}).get("pending"),
                "model_confirmed": (model_counts.get(code) or {}).get("confirmed"),
                "model_rejected": (model_counts.get(code) or {}).get("rejected"),
                "model_unknown": (model_counts.get(code) or {}).get("unknown"),
                "subcategory_summary": _position_subcategory_summary(positions),
                "subcategories": _position_subcategory_summary(positions),
                "evidence_line_count": len(evidence),
                "evidence_materials": [],
            }
            cards.append(card)
            continue
        cross_products = [
            product
            for product in products
            if str(product.get("category_code") or "") != code
        ]
        # EMBEDDED_ESTIMATE_PARSE_FIRST_V1: категория подтверждена разделом,
        # только если найденные товары лежат в разделе, а не в RESIDUE.
        _section_codes = sorted({
            str(p.get("section_code") or "").strip()
            for p in products
            if str(p.get("section_code") or "").strip().upper() not in ("", "RESIDUE")
        })
        _section_names = [
            str(p.get("section_name")).strip()
            for p in products
            if p.get("section_name")
        ]
        _object_match = compare_section_to_procurement(
            " ".join(_section_names) or (opp.get("category_name") or code),
            procurement_title=procurement_title,
            okpd_name=okpd_name,
            object_class=object_class,
        )
        material_value = round(
            sum(_number(p.get("total")) or 0.0 for p in products), 2
        ) if products else None
        model = model_counts.get(code)
        outcome = extraction_outcomes.get(code)
        routing_version = str(opp.get("routing_version") or "").strip()
        medal_authoritative = (
            track.upper() == "DIRECT_SUPPLY"
            or routing_version == "post_parse_rows_v1"
        )
        card = {
            "category_code": code,
            "category_name": opp.get("category_name") or code,
            "subcategory_name": opp.get("subcategory_name") or sub or None,
            "subcategory_code": None,
            "track": track or None,
            "status": opp.get("status"),
            "candidate_initial_score": (
                _number(opp.get("candidate_initial_score"))
                if medal_authoritative else None
            ),
            "candidate_initial_medal": (
                opp.get("candidate_initial_medal") if medal_authoritative else None
            ),
            "confirmed_base_score": (
                _number(opp.get("confirmed_base_score"))
                if medal_authoritative else None
            ),
            "confirmed_base_medal": (
                opp.get("confirmed_base_medal") if medal_authoritative else None
            ),
            "current_effective_score": (
                _number(opp.get("current_effective_score"))
                if medal_authoritative else None
            ),
            "current_effective_medal": (
                opp.get("current_effective_medal")
                if medal_authoritative else None
            ),
            "current_effective_reason": (
                opp.get("current_effective_reason") if medal_authoritative else None
            ),
            "section_confirmed": bool(_section_codes),
            "section_codes": _section_codes,
            "object_match": _object_match,
            "document_stage": _document_stage(queue_status, outcome),
            "document_progress": {
                "done": done_docs, "total": total_docs, "scope": "procurement",
            },
            "document_eta_seconds": eta,
            "model_stage": _model_stage(model),
            "model_pending": int((model or {}).get("pending") or 0) if model else None,
            "model_confirmed": int((model or {}).get("confirmed") or 0) if model else None,
            "model_rejected": int((model or {}).get("rejected") or 0) if model else None,
            "model_unknown": int((model or {}).get("unknown") or 0) if model else None,
            "model_eta_seconds": None,
            "model_completed_at": (model or {}).get("completed_at"),
            # Источника model-requested документов в DI пока нет: не выдумываем.
            "model_document_requests_count": None,
            "products": products,
            "product_count": len({
                str(p.get("material") or "").strip().lower()
                for p in products if p.get("material")
            }),
            "line_count": len(products),
            "source_row_count": sum(
                int(product.get("occurrence_count") or 1)
                for product in products
            ),
            "material_value": material_value,
            "quantities_by_unit": _quantities_by_unit(products),
            "cross_category_from": (
                ["drainage_water_management"] if cross_products else []
            ),
            "cross_category_line_count": len(cross_products),
            "evidence_only": False,
            "confirmed_goods": True,
            "factual_only": bool(opp.get("factual_only")),
            "render_kind": (
                "FACT_ONLY_GOODS"
                if opp.get("factual_only")
                else "CONFIRMED_GOODS"
            ),
            "evidence_line_count": 0,
            "evidence_materials": [],
        }
        for factual_subcategory, group_products in _factual_product_groups(
            products,
            category_code=code,
            opportunity_subcategory=sub,
        ).items():
            group_evidence = [
                dict(row)
                for row in evidence
                if str(row.get("category_code") or "") == code
                and str(row.get("subcategory_code") or "") == factual_subcategory
            ]
            group_cross = [
                product
                for product in group_products
                if str(product.get("category_code") or "") != code
            ]
            group_card = dict(card)
            group_card.update({
                "subcategory_code": factual_subcategory,
                "subcategory_name": (
                    opp.get("subcategory_name") or factual_subcategory
                ),
                "products": group_products,
                "product_count": len({
                    str(product.get("material") or "").strip().lower()
                    for product in group_products
                    if product.get("material")
                }),
                "line_count": len(group_products),
                "source_row_count": sum(
                    int(product.get("occurrence_count") or 1)
                    for product in group_products
                ),
                "material_value": round(
                    sum(
                        _number(product.get("total")) or 0.0
                        for product in group_products
                    ),
                    2,
                ),
                "quantities_by_unit": _quantities_by_unit(group_products),
                "evidence_line_count": len(group_evidence),
                "evidence_materials": group_evidence,
                "cross_category_from": (
                    ["drainage_water_management"] if group_cross else []
                ),
                "cross_category_line_count": len(group_cross),
            })
            cards.append(group_card)
    if category_positions is not None:
        return cards

    for evidence_row in evidence:
        code = str(evidence_row.get("category_code") or "").strip()
        sub = str(evidence_row.get("subcategory_code") or "").strip()
        if not code or not sub:
            continue
        key = (code, sub)
        if any(
            (
                str(card.get("category_code") or ""),
                str(card.get("subcategory_code") or ""),
            ) == key
            for card in cards
        ):
            continue
        opp = next(
            (
                row for row in opportunities or []
                if str(row.get("commercial_category_code") or "") == code
            ),
            {},
        )
        group_evidence = [
            dict(row) for row in evidence
            if str(row.get("category_code") or "") == code
            and str(row.get("subcategory_code") or "") == sub
        ]
        reference_rate_count = sum(
            1
            for row in group_evidence
            if str(row.get("layout_status") or "").upper()
            == "UNIT_RATE_ONLY"
            and _number(
                row.get("unit_price")
                if row.get("unit_price") is not None
                else row.get("unit_price_value")
            ) is not None
        )
        cards.append(
            {
                "category_code": code,
                "category_name": opp.get("category_name") or code,
                "subcategory_code": sub,
                "track": _EMBEDDED_TRACK,
                "status": "CURRENT",
                "candidate_initial_score": None,
                "candidate_initial_medal": None,
                "confirmed_base_score": None,
                "confirmed_base_medal": None,
                "current_effective_score": None,
                "current_effective_medal": None,
                "current_effective_reason": None,
                "section_confirmed": False,
                "section_codes": [],
                "object_match": {},
                "document_stage": _document_stage(
                    queue_status, extraction_outcomes.get(code)
                ),
                "document_progress": {
                    "done": done_docs,
                    "total": total_docs,
                    "scope": "procurement",
                },
                "document_eta_seconds": eta,
                "model_stage": _model_stage(model_counts.get(code)),
                "model_pending": None,
                "model_confirmed": None,
                "model_rejected": None,
                "model_unknown": None,
                "model_eta_seconds": None,
                "model_completed_at": None,
                "model_document_requests_count": None,
                "products": [],
                "product_count": len({
                    str(row.get("material") or row.get("product_name_raw") or "")
                    .strip()
                    .lower()
                    for row in group_evidence
                    if str(row.get("material") or row.get("product_name_raw") or "").strip()
                }),
                "line_count": 0,
                "source_row_count": 0,
                "evidence_line_count": len(group_evidence),
                "evidence_materials": group_evidence,
                "reference_rate_count": reference_rate_count,
                "material_value": None,
                "quantities_by_unit": {},
                "cross_category_from": [],
                "cross_category_line_count": 0,
                "evidence_only": True,
                "confirmed_goods": False,
                "factual_only": True,
                "render_kind": "EVIDENCE_ONLY",
            }
        )
    # EMBEDDED_CATEGORY_DISCOVERY_CONFIRMATION_V1: empty model categories are
    # not shown; only categories with real countable goods survive.
    unique_cards: List[Dict[str, Any]] = []
    seen_cards: set[tuple[str, str]] = set()
    for card in cards:
        if (
            int(card.get("line_count") or 0) <= 0
            and int(card.get("evidence_line_count") or 0) <= 0
        ):
            continue
        if (
            str(card.get("track") or "").upper() != "DIRECT_SUPPLY"
            and not str(card.get("subcategory_code") or "").strip()
        ):
            continue
        key = (
            str(card.get("category_code") or ""),
            str(card.get("subcategory_code") or ""),
        )
        if key in seen_cards:
            continue
        seen_cards.add(key)
        unique_cards.append(card)
    return unique_cards


def group_products_by_trust(products: Iterable[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Сгруппировать товары по trust-state, не смешивая подтверждённые и карантин."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for p in products or []:
        state = str(p.get("trust_state") or "").upper() or "UNKNOWN"
        buckets.setdefault(state, []).append(p)
    order = [
        "TRUSTED_PRODUCTION", "ESTIMATE_ROW_RESOLVED", "SECTION_CONFIRMED",
        "MANUAL_PROOF_QUARANTINE", "DEV_EXPOSED", "QUALITY_REJECTED",
    ]
    ordered = [(s, buckets.pop(s)) for s in order if s in buckets]
    ordered += [(s, buckets[s]) for s in sorted(buckets)]
    return ordered
