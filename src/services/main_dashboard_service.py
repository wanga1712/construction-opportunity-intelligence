"""Main dashboard (control room) — assembly of the live operational screen.

Single authority per widget (see ``main_dashboard_queries`` for the SQL):

active workset   : crm_procurements canonical actionable submission window
card medals      : torgi_workset_service.get_evaluated_torgi_workset
category matrix  : crm_product_categories x Second Pass category_evaluations
                   (fallback: crm_procurement_category_opportunities)
document pipeline: document_intelligence.document_files / document_matches
second pass      : procurement_ai_assessments, crm_v3_model_inference_runs

Failures are surfaced as ``ControlRoom.errors`` and never coerced to 0.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.services import main_dashboard_queries as q
from src.services.main_dashboard_types import (
    AUTHORITY_LABELS,
    BUCKET_LABELS,
    ERROR_LABELS,
    FAMILY_LABELS,
    MEDALS,
    CategoryRow,
    ControlRoom,
    LiveIndicator,
    Opportunity,
    Stage,
    classify_doc_error,
    deadline_bucket,
    format_age,
    freshness_status,
)

logger = logging.getLogger(__name__)

__all__ = [
    "load_control_room",
    "ControlRoom",
    "LiveIndicator",
    "Stage",
    "CategoryRow",
    "Opportunity",
    "format_age",
    "freshness_status",
    "deadline_bucket",
    "classify_doc_error",
    "MEDALS",
    "ERROR_LABELS",
    "AUTHORITY_LABELS",
    "FAMILY_LABELS",
    "BUCKET_LABELS",
]

_INDICATORS: List[Tuple[str, str, str]] = [
    ("CRM Sync", "crm_procurements · последняя запись/правка", "crm_sync"),
    ("Новая закупка", "crm_procurements · последний ingest", "new_procurement"),
    ("Queue Producer", "queue · последняя постановка задачи", "queue_producer"),
    ("Doc Worker", "queue · последняя завершённая задача", "doc_worker"),
    ("Second Pass", "model_inference_runs · последний запуск", "second_pass"),
]


def _age(stamp: Optional[datetime]) -> Optional[float]:
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def load_indicators(stamps: Dict[str, Tuple[Optional[datetime], Optional[str]]]) -> List[LiveIndicator]:
    out: List[LiveIndicator] = []
    for label, caption, key in _INDICATORS:
        stamp, error = stamps.get(key, (None, "NO_PROBE"))
        if error:
            out.append(LiveIndicator(label=label, caption=caption, status="UNKNOWN", error=error))
            continue
        age = _age(stamp)
        out.append(
            LiveIndicator(
                label=label,
                caption=caption,
                age_seconds=age,
                status=freshness_status(age),
                stamp=stamp,
            )
        )
    return out


def _build_categories(
    registry: List[Tuple[str, str]],
    medal_rows: List[Tuple[int, str, str, str]],
    doc_files: Dict[int, Tuple[int, int, int]],
) -> List[CategoryRow]:
    rows: Dict[str, CategoryRow] = {code: CategoryRow(code=code, name=name) for code, name in registry}
    seen: set = set()
    for pid, cat, medal, src in medal_rows:
        if medal not in MEDALS or cat not in rows:
            continue
        if (pid, cat) in seen:
            continue
        seen.add((pid, cat))
        row = rows[cat]
        row.active += 1
        if src == "SECOND_PASS":
            row.second_pass += 1
        if medal == "GOLD":
            row.gold += 1
        elif medal == "SILVER":
            row.silver += 1
        elif medal == "BRONZE":
            row.bronze += 1
        else:
            row.wood += 1
        if doc_files.get(pid, (0, 0, 0))[0] > 0:
            row.with_docs += 1
        else:
            row.waiting_docs += 1
    return list(rows.values())


def _best_category(medal_rows: List[Tuple[int, str, str, str]]) -> Dict[int, Tuple[str, str]]:
    order = {m: i for i, m in enumerate(MEDALS)}
    best: Dict[int, Tuple[str, str]] = {}
    for pid, cat, medal, _src in medal_rows:
        if medal not in MEDALS:
            continue
        current = best.get(pid)
        if current is None or order.get(medal, 99) < order.get(current[1], 99):
            best[pid] = (cat, medal)
    return best


def load_control_room() -> ControlRoom:
    """Assemble the full control-room snapshot. Never raises."""
    t0 = time.perf_counter()
    room = ControlRoom()

    try:
        room.indicators = load_indicators(q.load_freshness_stamps())
    except Exception as exc:  # noqa: BLE001
        room.errors.append(f"indicators: {type(exc).__name__}: {exc}")

    try:
        active_rows = q.load_active_rows()
    except Exception as exc:  # noqa: BLE001
        room.errors.append(f"active workset: {type(exc).__name__}: {exc}")
        room.load_seconds = time.perf_counter() - t0
        return room

    ids = [int(r[0]) for r in active_rows]
    room.active_total = len(ids)
    price_by_id = {int(r[0]): float(r[4] or 0) for r in active_rows}

    # 24h window is decided by the database clock, not by the app's timezone.
    new_by_id = {int(r[0]): bool(r[5]) for r in active_rows}
    room.new_24h = sum(1 for pid in ids if new_by_id.get(pid))

    stats = q.load_doc_stats(ids)
    if stats.get("error"):
        room.errors.append(f"document stats: {stats['error']}")
    doc_files: Dict[int, Tuple[int, int, int]] = stats.get("files") or {}
    doc_matches: Dict[int, int] = stats.get("matches") or {}

    levels: Dict[int, Tuple[bool, str]] = {}
    try:
        levels = q.load_assessment_levels(ids)
    except Exception as exc:  # noqa: BLE001
        room.errors.append(f"second pass: {type(exc).__name__}: {exc}")

    registry: List[Tuple[str, str]] = []
    try:
        registry = q.load_category_registry()
    except Exception as exc:  # noqa: BLE001
        room.errors.append(f"category registry: {type(exc).__name__}: {exc}")

    medal_rows: List[Tuple[int, str, str, str]] = []
    try:
        medal_rows = q.load_category_medals()
    except Exception as exc:  # noqa: BLE001
        room.errors.append(f"category medals: {type(exc).__name__}: {exc}")

    room.categories = _build_categories(registry, medal_rows, doc_files)
    best_cat = _best_category(medal_rows)
    names = dict(registry)

    with_docs = sum(1 for pid in ids if doc_files.get(pid, (0, 0, 0))[0] > 0)
    docs_complete = sum(1 for pid in ids if doc_files.get(pid, (0, 0, 0))[1] > 0)
    failed_docs = sum(1 for pid in ids if doc_files.get(pid, (0, 0, 0))[2] > 0)
    evidence = sum(1 for pid in ids if doc_matches.get(pid, 0) > 0)
    second_pass = sum(1 for pid in ids if levels.get(pid, (False, ""))[0])
    model_medal = sum(1 for pid in ids if levels.get(pid, (False, ""))[1] in MEDALS)

    room.with_docs = with_docs
    room.docs_complete = docs_complete
    room.second_pass = second_pass
    room.stages = [
        Stage("active", "АКТИВНЫЕ", len(ids)),
        Stage("links", "ЕСТЬ ДОКУМЕНТЫ", with_docs),
        Stage("completed", "ДОКУМЕНТЫ ОБРАБОТАНЫ", docs_complete),
        Stage("evidence", "EVIDENCE ГОТОВ", evidence),
        Stage("second_pass", "SECOND PASS", second_pass),
        Stage("model_medal", "MODEL MEDAL", model_medal),
    ]
    room.gaps = {
        "no_links": max(len(ids) - with_docs, 0),
        "waiting_docs": max(with_docs - docs_complete, 0),
        "no_evidence": max(docs_complete - evidence, 0),
        "waiting_second_pass": max(evidence - second_pass, 0),
        "download_errors": failed_docs,
    }

    try:
        from src.services.torgi_workset_service import get_evaluated_torgi_workset

        cards = get_evaluated_torgi_workset(hide_expired=True)
    except Exception as exc:  # noqa: BLE001
        room.errors.append(f"workset cards: {type(exc).__name__}: {exc}")
        cards = []

    authority: Dict[str, int] = {}
    families: Dict[str, int] = {}
    deadlines: Dict[str, int] = {key: 0 for key in BUCKET_LABELS}
    decay = 0
    for card in cards:
        auth = str(card.get("base_medal_authority") or "UNASSESSED")
        authority[auth] = authority.get(auth, 0) + 1
        fam = str(card.get("object_family") or "OTHER")
        families[fam] = families.get(fam, 0) + 1
        bucket = deadline_bucket(card.get("days_to_deadline"))
        deadlines[bucket] = deadlines.get(bucket, 0) + 1
        if (card.get("deadline_decay_steps") or 0) > 0:
            decay += 1

    room.authority = authority
    room.families = families
    room.deadlines = {k: v for k, v in deadlines.items() if v}
    room.decay_affected = decay if cards else None
    room.model_authority = authority.get("SECOND_PASS_MODEL")

    for card in cards[:10]:
        pid = int(card.get("id") or 0)
        cat_code, cat_medal = best_cat.get(pid, ("", ""))
        room.opportunities.append(
            Opportunity(
                crm_id=pid,
                contract_number=str(card.get("contract_number") or ""),
                title=str(card.get("auction_name") or "")[:120],
                effective_medal=str(card.get("effective_medal") or "UNASSESSED"),
                base_authority=str(card.get("base_medal_authority") or "UNASSESSED"),
                category=names.get(cat_code, cat_code) or "—",
                category_medal=cat_medal or "—",
                initial_price=price_by_id.get(pid, 0.0),
                days_left=card.get("days_to_deadline"),
            )
        )

    rows, err = q.load_doc_error_rows()
    if err:
        room.errors.append(f"document errors: {err}")
        room.doc_errors_total = None
    else:
        buckets: Dict[str, int] = {}
        total = 0
        for message, status, cnt in rows:
            cnt = int(cnt)
            total += cnt
            key = classify_doc_error(message, status)
            buckets[key] = buckets.get(key, 0) + cnt
        room.doc_errors = sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0]))
        room.doc_errors_total = total

    room.load_seconds = time.perf_counter() - t0
    return room