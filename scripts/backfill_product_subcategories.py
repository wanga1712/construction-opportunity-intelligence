#!/usr/bin/env python3
"""Deterministic product-subcategory backfill for existing opportunities.

Reads ``crm_procurement_category_opportunities`` rows that are UNCLASSIFIED
(NULL / empty / literal ``SUBCATEGORY_NOT_ASSIGNED``) and fills
``commercial_subcategory_code`` (plus source/confidence) using the deterministic
resolver. No model, no Qwen. Without ``--apply`` it writes nothing.

Usage:
    python scripts/backfill_product_subcategories.py --dry-run --limit 100
    python scripts/backfill_product_subcategories.py --apply --limit 100
    python scripts/backfill_product_subcategories.py --dry-run --category computers --limit 50
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.infrastructure.crm_connection import connect_crm  # noqa: E402
from src.services import product_subcategory_resolver as resolver  # noqa: E402

UNCLASSIFIED_SQL = (
    "(o.commercial_subcategory_code IS NULL"
    " OR btrim(o.commercial_subcategory_code) = ''"
    f" OR o.commercial_subcategory_code = '{resolver.UNCLASSIFIED_SENTINEL}')"
)


def _rows(cur, sql, params=None):
    cur.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def build_context(cur) -> resolver.ResolverContext:
    product: Dict[str, set] = {}
    for r in _rows(
        cur,
        """
        SELECT c.category_code, s.subcategory_code
        FROM crm_product_subcategories s
        JOIN crm_product_categories c ON c.id = s.category_id
        WHERE s.is_active = TRUE AND s.subcategory_kind = 'PRODUCT'
        """,
    ):
        product.setdefault(r["category_code"], set()).add(r["subcategory_code"])

    terms: Dict[str, Dict[str, Dict[str, List[Tuple[str, float]]]]] = {}
    for r in _rows(
        cur,
        """
        SELECT c.category_code, s.subcategory_code, t.term_type, t.phrase, t.weight
        FROM crm_product_subcategory_terms t
        JOIN crm_product_subcategories s ON s.id = t.subcategory_id
        JOIN crm_product_categories c ON c.id = s.category_id
        WHERE s.is_active = TRUE AND s.subcategory_kind = 'PRODUCT' AND t.is_active
        """,
    ):
        terms.setdefault(r["category_code"], {}).setdefault(
            r["subcategory_code"], {}
        ).setdefault(r["term_type"], []).append(
            (r["phrase"], float(r["weight"] or 100))
        )
    return resolver.ResolverContext(product_by_category=product, terms_by_category=terms)


def select_candidates(
    cur, categories: Sequence[str], limit: int, per_category_limit: int = 0,
    track: str = "",
) -> List[Dict[str, Any]]:
    where_cat = ""
    params: List[Any] = []
    if categories:
        where_cat = "AND o.commercial_category_code = ANY(%s)"
        params.append(list(categories))
    if track:
        where_track = "AND o.opportunity_track = %s"
        params.append(track)
    else:
        where_track = ""
    if per_category_limit:
        rank_cte = f""",
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY category_code
                ORDER BY amount DESC NULLS LAST, procurement_id) AS rn
            FROM cand
        )"""
        source = "ranked"
        rank_filter = f"WHERE rn <= {int(per_category_limit)}"
    else:
        rank_cte = ""
        source = "cand"
        rank_filter = ""
    limit_sql = ""
    if limit and limit > 0:
        limit_sql = "LIMIT %s"
        params.append(limit)
    return _rows(
        cur,
        f"""
        WITH cand AS (
            SELECT DISTINCT ON (o.procurement_id, o.commercial_category_code,
                                o.opportunity_track, o.routing_version)
                   o.id, o.procurement_id,
                   o.commercial_category_code AS category_code,
                   o.opportunity_track,
                   p.initial_price AS amount, p.auction_name AS title
            FROM crm_procurement_category_opportunities o
            LEFT JOIN crm_procurements p ON p.id = o.procurement_id
            WHERE o.status = 'CURRENT' AND {UNCLASSIFIED_SQL}
              {where_cat}
              {where_track}
            ORDER BY o.procurement_id, o.commercial_category_code,
                     o.opportunity_track, o.routing_version, o.id
        ){rank_cte}
        SELECT * FROM {source}
        {rank_filter}
        ORDER BY category_code, amount DESC NULLS LAST, procurement_id
        {limit_sql}
        """,
        params,
    )


def load_facts(cur, candidates: List[Dict[str, Any]]):
    proc_ids = sorted({c["procurement_id"] for c in candidates})
    bridge = {
        r["id"]: (r["source_table"], r["source_id"])
        for r in _rows(
            cur,
            "SELECT id, source_table, source_id FROM crm_procurements WHERE id = ANY(%s)",
            (proc_ids,),
        )
    }
    tender_ids = sorted({sid for (_t, sid) in bridge.values() if sid is not None})

    def key(pair):
        return f"{pair[0]}::{pair[1]}"

    doc_facts: Dict[str, List[Tuple[str, str]]] = {}
    if tender_ids:
        for r in _rows(
            cur,
            """SELECT registry_type, tender_id, category_code, subcategory_code
               FROM crm_object_subcategory_links
               WHERE tender_id = ANY(%s) AND subcategory_code IS NOT NULL""",
            (tender_ids,),
        ):
            doc_facts.setdefault(key((r["registry_type"], r["tender_id"])), []).append(
                (r["category_code"], r["subcategory_code"])
            )

    comp_items: Dict[str, List[str]] = {}
    if tender_ids:
        for r in _rows(
            cur,
            """SELECT registry_type, tender_id, category FROM crm_computer_tz_items
               WHERE tender_id = ANY(%s) AND category IS NOT NULL""",
            (tender_ids,),
        ):
            comp_items.setdefault(key((r["registry_type"], r["tender_id"])), []).append(
                r["category"]
            )

    tz_text: Dict[str, str] = {}
    if tender_ids:
        for r in _rows(
            cur,
            """SELECT registry_type, tender_id, tz_text_excerpt
               FROM crm_computer_tz_cards WHERE tender_id = ANY(%s)""",
            (tender_ids,),
        ):
            if r["tz_text_excerpt"]:
                tz_text[key((r["registry_type"], r["tender_id"]))] = r["tz_text_excerpt"]
    return bridge, doc_facts, comp_items, tz_text


def resolve_candidates(candidates, ctx, bridge, doc_facts, comp_items, tz_text):
    results = []
    for c in candidates:
        bkey = bridge.get(c["procurement_id"])
        k = f"{bkey[0]}::{bkey[1]}" if bkey else None
        inp = resolver.ResolverInput(
            category_code=c["category_code"],
            title=c.get("title") or "",
            tz_text=(tz_text.get(k) or "") if k else "",
            doc_facts=tuple(doc_facts.get(k, ())) if k else (),
            computer_categories=tuple(comp_items.get(k, ())) if k else (),
            allow_term_match=(str(c.get("opportunity_track") or "").upper()
                              == "DIRECT_SUPPLY"),
        )
        res = resolver.resolve(inp, ctx)
        results.append((c, res))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--per-category-limit", type=int, default=0)
    ap.add_argument("--category", action="append", default=[])
    ap.add_argument("--track", default="")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    if args.apply and args.dry_run:
        print("choose either --dry-run or --apply")
        return 2

    conn = connect_crm()
    cur = conn.cursor()
    ctx = build_context(cur)
    candidates = select_candidates(
        cur, args.category, args.limit, args.per_category_limit, args.track
    )
    bridge, doc_facts, comp_items, tz_text = load_facts(cur, candidates)
    results = resolve_candidates(candidates, ctx, bridge, doc_facts, comp_items, tz_text)

    selected = len(results)
    resolved = sum(1 for _c, r in results if r.subcategory_code)
    ambiguous = sum(1 for _c, r in results if r.reason.startswith("ambiguous"))
    no_match = selected - resolved - ambiguous

    report = []
    for c, r in results:
        report.append({
            "category": c["category_code"],
            "procurement_id": c["procurement_id"],
            "opportunity_id": c["id"],
            "title": (c.get("title") or "")[:120],
            "old_subcategory": None,
            "new_subcategory": r.subcategory_code,
            "source": r.source,
            "confidence": r.confidence,
            "reason": r.reason,
        })

    print(f"SELECTED={selected} RESOLVED={resolved} AMBIGUOUS={ambiguous} NO_MATCH={no_match}")
    for row in report:
        print(
            f"  {row['category']}/{row['procurement_id']} -> "
            f"{row['new_subcategory'] or 'NULL'} ({row['source'] or row['reason']}, "
            f"{row['confidence']}) | {row['title'][:60]}"
        )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(
                {"selected": selected, "resolved": resolved, "ambiguous": ambiguous,
                 "no_match": no_match, "rows": report},
                fh, ensure_ascii=False, indent=2,
            )

    if args.apply:
        written = 0
        for c, r in results:
            if not r.subcategory_code:
                continue
            cur.execute(
                """
                UPDATE crm_procurement_category_opportunities
                   SET commercial_subcategory_code = %s,
                       commercial_subcategory_source = %s,
                       commercial_subcategory_confidence = %s,
                       updated_at = NOW()
                 WHERE id = %s AND status = 'CURRENT'
                   AND commercial_subcategory_code IS NULL
                """,
                (r.subcategory_code, r.source, r.confidence, c["id"]),
            )
            written += cur.rowcount
        conn.commit()
        print(f"APPLIED={written}")
    else:
        conn.rollback()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
