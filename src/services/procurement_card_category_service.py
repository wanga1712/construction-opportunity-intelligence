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
    "MANUAL_PROOF_QUARANTINE": "ОЖИДАЕТ ПРОВЕРКИ",
    "DEV_EXPOSED": "ТЕХНИЧЕСКИЙ КАНДИДАТ",
    "QUALITY_REJECTED": "ОТКЛОНЕНО КАЧЕСТВОМ",
}

_PENDING_VALIDATION = ("UNKNOWN", "RAW", "PENDING")


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


def build_category_cards(
    *,
    opportunities: Iterable[Dict[str, Any]],
    supply_facts: Iterable[Dict[str, Any]],
    documents: Iterable[Dict[str, Any]],
    queue_progress: Dict[str, Any],
    procurement_id: int,
    model_counts: Dict[str, Dict[str, Any]],
    extraction_outcomes: Dict[str, Dict[str, Any]],
    procurement_title: Any = None,
    okpd_name: Any = None,
    object_class: Any = None,
) -> List[Dict[str, Any]]:
    """Собрать карточки категорий (одна opportunity = один блок)."""
    from src.services.document_queue_progress_service import queue_eta_seconds
    from src.services.object_section_match_service import compare_section_to_procurement

    facts = list(supply_facts or [])
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

        products = _products_for_category(facts, code)
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
        cards.append({
            "category_code": code,
            "category_name": opp.get("category_name") or code,
            "subcategory_code": sub or None,
            "track": track or None,
            "status": opp.get("status"),
            "candidate_initial_score": _number(opp.get("candidate_initial_score")),
            "candidate_initial_medal": opp.get("candidate_initial_medal"),
            "confirmed_base_score": _number(opp.get("confirmed_base_score")),
            "confirmed_base_medal": opp.get("confirmed_base_medal"),
            "current_effective_score": _number(opp.get("current_effective_score")),
            "current_effective_medal": opp.get("current_effective_medal"),
            "current_effective_reason": opp.get("current_effective_reason"),
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
            "material_value": material_value,
            "quantities_by_unit": _quantities_by_unit(products),
        })
    return cards


def group_products_by_trust(products: Iterable[Dict[str, Any]]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Сгруппировать товары по trust-state, не смешивая подтверждённые и карантин."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for p in products or []:
        state = str(p.get("trust_state") or "").upper() or "UNKNOWN"
        buckets.setdefault(state, []).append(p)
    order = ["TRUSTED_PRODUCTION", "MANUAL_PROOF_QUARANTINE", "DEV_EXPOSED", "QUALITY_REJECTED"]
    ordered = [(s, buckets.pop(s)) for s in order if s in buckets]
    ordered += [(s, buckets[s]) for s in sorted(buckets)]
    return ordered
