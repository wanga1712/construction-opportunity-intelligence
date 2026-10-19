#!/usr/bin/env python3
"""EMBEDDED_ESTIMATE_PARSE_FIRST_V1 — dry-run: подтверждение категории разделом.

Read-only аудит: что было бы с confirmed_base, если категорию подтверждать
ТОЛЬКО товарными фактами внутри раздела сметы (`section_code` не пустой и не
RESIDUE), а не любыми TRUSTED_PRODUCTION фактами.

Пороги/веса медали не меняются — используется та же формула, что в
`scripts/write_confirmed_base.py`. Запуск без `--write` (и `--write` здесь нет):
скрипт ничего не пишет.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.works_vs_goods_service import classify_fact_kind  # noqa: E402

DIRECT_CATS = {"computers", "cable_support_systems"}


def di_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def crm_dsn() -> Dict[str, Any]:
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    return dict(require_crm_db_connect_kwargs())


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _pct_rank(values: List[float], value: float) -> Optional[float]:
    if not values:
        return None
    below = sum(1 for v in values if v <= value)
    return 100.0 * below / len(values)


def _score(o: Dict[str, Any], agg: Dict[str, Any], cohort: List[float]) -> float:
    track = "DIRECT" if o["category_code"] in DIRECT_CATS else "EMBEDDED"
    has_value = bool(agg["vrows"])
    has_qty = bool(agg["qty"])
    comps: Dict[str, Optional[float]] = {
        "evidence": 1.0 if has_value else (0.6 if has_qty else 0.3),
        "value": (_pct_rank(cohort, float(agg["vsum"])) or 0) / 100.0 if has_value else None,
    }
    end = o.get("execution_end_at") or o.get("delivery_end_date") or o.get("end_date")
    try:
        end_d = end.date() if hasattr(end, "date") else (date.fromisoformat(str(end)) if end else None)
    except Exception:
        end_d = None
    days = (end_d - datetime.now(timezone.utc).date()).days if end_d else None
    comps["timing"] = None if days is None else (
        1.0 if days >= 90 else 0.7 if days >= 30 else 0.4 if days >= 0 else 0.0
    )
    comps["category_signal"] = {
        "GOLD": 1.0, "SILVER": 0.8, "BRONZE": 0.6, "WOOD": 0.3,
    }.get((o.get("candidate_initial_medal") or "").upper(), 0.5)
    comps["actionability"] = 1.0 if (o.get("commercial_state") or "").upper() in {"OPEN", "ACTIVE"} else 0.6
    weights = (
        {"evidence": 0.25, "value": 0.30, "timing": 0.15, "category_signal": 0.15, "actionability": 0.15}
        if track == "DIRECT" else
        {"evidence": 0.35, "value": 0.15, "timing": 0.15, "category_signal": 0.20, "actionability": 0.15}
    )
    avail = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(weights[k] for k in avail) or 1.0
    score = 100.0 * sum(weights[k] * avail[k] for k in avail) / wsum
    if track == "EMBEDDED" and not has_value:
        score = min(score, 74.99)
    return score


def medal_for(score: float) -> str:
    return "GOLD" if score >= 85 else "SILVER" if score >= 70 else "BRONZE" if score >= 50 else "WOOD"


def main() -> int:
    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        opps = query(crm, """
            SELECT o.id, o.procurement_id, o.commercial_category_code AS category_code,
                   o.opportunity_track, o.commercial_state, o.candidate_initial_medal,
                   o.confirmed_base_medal, p.execution_end_at, p.delivery_end_date, p.end_date
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
        rows = query(di, """
            SELECT procurement_id, category_code, section_code, entity_type,
                   product_name_raw, product_name_normalized,
                   quantity_value, quantity_unit_normalized,
                   unit_price_value, total_price_value, structured_fact_trust_state
              FROM structured_entities
             WHERE structured_fact_trust_state = 'TRUSTED_PRODUCTION'
               AND category_code IS NOT NULL AND category_code <> 'unknown'
        """)
    finally:
        crm.close()
        di.close()

    agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"facts": 0, "qty": 0, "vrows": 0, "vsum": 0.0}
    )
    goods_by_cat: Counter = Counter()
    work_by_cat: Counter = Counter()
    for r in rows:
        kind = classify_fact_kind(
            entity_type=r.get("entity_type"),
            name=r.get("product_name_normalized") or r.get("product_name_raw"),
        )
        if kind != "GOODS":
            work_by_cat[r["category_code"]] += 1
            continue
        goods_by_cat[r["category_code"]] += 1
        section = str(r.get("section_code") or "").strip()
        in_section = bool(section) and section.upper() != "RESIDUE"
        key = (int(r["procurement_id"]), r["category_code"], "SECTION" if in_section else "RESIDUE")
        a = agg[key]
        a["facts"] += 1
        if r.get("quantity_value") is not None and r.get("quantity_unit_normalized"):
            a["qty"] += 1
        if r.get("total_price_value") is not None:
            a["vrows"] += 1
            a["vsum"] += float(r["total_price_value"])

    cohort: Dict[str, List[float]] = defaultdict(list)
    for (pid, cat, scope), a in agg.items():
        if scope == "SECTION" and a["vrows"]:
            cohort[cat].append(float(a["vsum"]))

    would_keep = would_lose = no_section = 0
    changes: List[tuple] = []
    dist = Counter()
    for o in opps:
        key = (int(o["procurement_id"]), o["category_code"], "SECTION")
        a = agg.get(key)
        if not a or not a["facts"]:
            no_section += 1
            if o.get("confirmed_base_medal"):
                would_lose += 1
                changes.append((o, None, "NO_SECTION_FACTS"))
            continue
        score = _score(o, a, cohort[o["category_code"]])
        medal = medal_for(score)
        dist[medal] += 1
        would_keep += 1
        if o.get("confirmed_base_medal") != medal:
            changes.append((o, (round(score, 2), medal), "CHANGED"))

    print("ESTIMATE_FIRST_CONFIRMATION_AUDIT=DRY_RUN")
    print(f"CURRENT_OPPORTUNITIES={len(opps)}")
    print(f"GOODS_FACTS_TOTAL={sum(goods_by_cat.values())}")
    print(f"GOODS_FACTS_IN_SECTION={sum(a['facts'] for (p, c, s), a in agg.items() if s == 'SECTION')}")
    print(f"GOODS_FACTS_RESIDUE={sum(a['facts'] for (p, c, s), a in agg.items() if s == 'RESIDUE')}")
    print(f"WORK_FACTS_EXCLUDED={sum(work_by_cat.values())}")
    print(f"OPPORTUNITIES_WITH_SECTION_FACTS={would_keep}")
    print(f"OPPORTUNITIES_WITHOUT_SECTION_FACTS={no_section}")
    print(f"CONFIRMED_BASE_WOULD_LOSE={would_lose}")
    print(f"CONFIRMED_BASE_DISTRIBUTION={dict(dist)}")
    print("TOP_CATEGORIES_BY_SECTION_FACTS:")
    sec_by_cat = Counter()
    for (pid, cat, scope), a in agg.items():
        if scope == "SECTION":
            sec_by_cat[cat] += a["facts"]
    for cat, n in sec_by_cat.most_common(10):
        total = goods_by_cat[cat] or 1
        print(f"  {cat}: section={n} / goods={goods_by_cat[cat]} ({100*n/total:.1f}%)")
    print("SAMPLE_WOULD_LOSE_OR_CHANGE:")
    for o, target, reason in changes[:15]:
        print(
            f"  pid={o['procurement_id']} {o['category_code']} "
            f"confirmed={o.get('confirmed_base_medal') or '-'} -> "
            f"{target if target else 'NULL'} ({reason})"
        )
    print("DB_WRITES=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
