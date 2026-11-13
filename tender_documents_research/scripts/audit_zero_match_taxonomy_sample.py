#!/usr/bin/env python3
"""Audit a deterministic stratified sample from proven ZERO_MATCH coverage."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CRM_ROOT = Path("/opt/CRM_Streamlit")
for path in (ROOT, CRM_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from document_processor.estimate_row_normalization_authority import (
    NORMALIZER_VERSION,
)
from document_processor.estimate_row_taxonomy import (
    load_taxonomy,
    normalize_text,
)
from document_processor.parse_extractors import _connect
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

load_dotenv("/opt/CRM_Streamlit/.env", override=True)


def _crm_connect():
    return psycopg2.connect(**dict(require_crm_db_connect_kwargs()))


def _size_bucket(rows: int) -> str:
    if rows <= 50:
        return "small"
    if rows <= 500:
        return "medium"
    return "large"


def _load_cards(cur) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT p.procurement_id, p.rows_expected
          FROM estimate_row_normalization_procurements p
          JOIN estimate_row_normalization_runs r ON r.id=p.run_id
         WHERE r.run_kind='HISTORICAL_APPLIED_REPORT_IMPORT'
           AND r.proof_source='HISTORICAL_APPLIED_REPORT'
           AND p.status='COMPLETED'
           AND p.rows_matched=0
         ORDER BY p.procurement_id
        """
    )
    return [dict(row) for row in cur.fetchall()]


def _stratify_cards(cards: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    strata: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        card["size_bucket"] = _size_bucket(int(card["rows_expected"]))
        strata[card["size_bucket"]].append(card)
    allocation = {"small": 17, "medium": 17, "large": 16}
    selected = []
    for bucket, target in allocation.items():
        values = sorted(
            strata.get(bucket, []),
            key=lambda item: (
                str(item.get("scope_type") or ""),
                int(item["procurement_id"]),
            ),
        )
        if not values:
            continue
        if len(values) <= target:
            selected.extend(values)
            continue
        indexes = {
            round(index * (len(values) - 1) / max(target - 1, 1))
            for index in range(target)
        }
        selected.extend(values[index] for index in sorted(indexes))
    return selected[:limit]


def _candidate_trace(taxonomy: Any, text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    scores: dict[tuple[str, str], float] = {}
    positive_terms: dict[tuple[str, str], list[str]] = defaultdict(list)
    negative_hits: list[dict[str, str]] = []
    for term in taxonomy.terms:
        if not term.pattern.search(normalized):
            continue
        key = (term.category_code, term.subcategory_code)
        if term.term_type == "negative":
            negative_hits.append(
                {
                    "category_code": term.category_code,
                    "subcategory_code": term.subcategory_code,
                    "term": term.phrase,
                }
            )
            continue
        scores[key] = scores.get(key, 0.0) + term.weight
        positive_terms[key].append(term.phrase)
    candidates = [
        {
            "category_code": key[0],
            "subcategory_code": key[1],
            "score": score,
            "terms": sorted(positive_terms[key])[:8],
        }
        for key, score in sorted(
            scores.items(), key=lambda item: (-item[1], item[0])
        )[:8]
    ]
    resolution = taxonomy.resolve(text)
    if resolution.category_code:
        row_class = "Z4_NORMALIZATION_LOSS"
    elif negative_hits:
        row_class = "Z3_BLOCKED_BY_NEGATIVE_TERM"
    elif resolution.reason == "semantic_guard_rejected":
        row_class = "Z6_SUBCATEGORY_SIGNAL_ONLY"
    elif candidates:
        row_class = "Z5_CATEGORY_EXISTS_DICTIONARY_MISS"
    else:
        row_class = "Z2_MATERIAL_LIKE_NO_TERM_MATCH"
    return {
        "normalized_text": normalized[:1000],
        "category_candidates": candidates,
        "negative_term_hits": negative_hits[:20],
        "resolver_category_code": resolution.category_code,
        "resolver_subcategory_code": resolution.subcategory_code,
        "resolver_reason": resolution.reason,
        "resolver_matched_terms": list(resolution.matched_terms[:20]),
        "classification": row_class,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", type=int, default=50)
    parser.add_argument("--rows", type=int, default=100)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    di = _connect()
    crm = _crm_connect()
    try:
        with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            all_cards = _load_cards(cur)
        with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT p.id AS procurement_id,
                       coalesce(a.procurement_scope_type, p.source_table, 'UNKNOWN')
                           AS scope_type
                  FROM crm_procurements p
                  LEFT JOIN crm_procurement_scope_authority a
                    ON a.procurement_id=p.id
                 WHERE p.id=ANY(%s)
                """,
                ([int(card["procurement_id"]) for card in all_cards],),
            )
            scope_by_pid = {
                int(row["procurement_id"]): row["scope_type"]
                for row in cur.fetchall()
            }
        for card in all_cards:
            card["scope_type"] = scope_by_pid.get(
                int(card["procurement_id"]), "UNKNOWN"
            )
        cards = _stratify_cards(all_cards, args.cards)
        taxonomy = load_taxonomy(crm)
        pids = [int(card["procurement_id"]) for card in cards]
        with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, procurement_id, source_document_id, row_ref,
                       name_raw, name_normalized, category_code,
                       subcategory_code, source_quote, row_kind
                  FROM structured_estimate_rows
                 WHERE procurement_id=ANY(%s) AND row_kind='GOODS'
                 ORDER BY procurement_id, id
                """,
                (pids,),
            )
            rows_by_pid: dict[int, list[dict]] = defaultdict(list)
            for row in cur.fetchall():
                rows_by_pid[int(row["procurement_id"])].append(dict(row))
        selected_rows = []
        depth = 0
        while len(selected_rows) < args.rows and depth < 20:
            added = False
            for pid in pids:
                values = rows_by_pid.get(pid, [])
                if depth < len(values):
                    selected_rows.append(values[depth])
                    added = True
                    if len(selected_rows) >= args.rows:
                        break
            if not added:
                break
            depth += 1
        traces = []
        for row in selected_rows:
            text = " ".join(
                filter(
                    None,
                    [
                        str(row.get("name_raw") or ""),
                        str(row.get("source_quote") or ""),
                    ],
                )
            )
            traces.append(
                {
                    "procurement_id": int(row["procurement_id"]),
                    "estimate_row_id": int(row["id"]),
                    "source_document_id": row.get("source_document_id"),
                    "row_ref": row.get("row_ref"),
                    "raw_name": row.get("name_raw"),
                    "normalized_name": row.get("name_normalized"),
                    "category_before": row.get("category_code"),
                    "subcategory_before": row.get("subcategory_code"),
                    **_candidate_trace(taxonomy, text),
                }
            )
        class_counts = Counter(item["classification"] for item in traces)
        result = {
            "normalizer_version": NORMALIZER_VERSION,
            "zero_match_cohort": sum(
                1 for card in cards if int(card["rows_expected"]) >= 0
            ),
            "sample_cards": len(cards),
            "sample_rows": len(traces),
            "size_buckets": dict(Counter(card["size_bucket"] for card in cards)),
            "scope_types": dict(Counter(card["scope_type"] for card in cards)),
            "classification_counts": dict(sorted(class_counts.items())),
            "cards": cards,
            "rows": traces,
        }
        Path(args.report).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    finally:
        crm.rollback()
        di.rollback()
        crm.close()
        di.close()
    print(
        json.dumps(
            {
                "sample_cards": result["sample_cards"],
                "sample_rows": result["sample_rows"],
                "classification_counts": result["classification_counts"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
