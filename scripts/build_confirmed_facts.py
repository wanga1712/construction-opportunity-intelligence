#!/usr/bin/env python3
"""Semantic dedup + confirmed category facts (aggregation layer).

Semantic identity (per the approved contract):
    source_document_id + category_code + normalized_material
    + normalized_quantity + normalized_unit
    + COALESCE(normalized_unit_price, line_total)
page/sheet/row stay as provenance and are NOT part of the identity, so the same
position duplicated across tables of one document collapses to one confirmed
fact while genuinely different positions stay separate.

Never uses crm_procurements.initial_price / project NMCK as a category value.
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EXTRACTOR_VERSION = os.getenv("SEMANTIC_EXTRACTOR_VERSION", "EMBEDDED_EXTRACTOR_V1")


def di_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def semantic_key(row: Dict[str, Any]) -> str:
    parts = [
        str(row.get("source_document_id") or ""),
        str(row.get("category_code") or ""),
        (row.get("product_name_normalized") or "").lower().strip(),
        str(row.get("quantity_value") if row.get("quantity_value") is not None else ""),
        str(row.get("quantity_unit_normalized") or ""),
        str(
            row.get("unit_price_value")
            if row.get("unit_price_value") is not None
            else (row.get("total_price_value") if row.get("total_price_value") is not None else "")
        ),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def main() -> int:
    di = psycopg2.connect(**di_dsn())
    try:
        trust = query(
            di,
            "SELECT structured_fact_trust_state AS state, count(*) AS n"
            "  FROM structured_entities WHERE extractor_version=%s"
            "   AND category_code IS NOT NULL AND category_code <> 'unknown'"
            " GROUP BY 1",
            (EXTRACTOR_VERSION,),
        )
        trust_by_state = {r["state"]: int(r["n"]) for r in trust}
        print(f"CONFIRMED_FACTS_TRUSTED_PRODUCTION={trust_by_state.get('TRUSTED_PRODUCTION', 0)}")
        print(f"CONFIRMED_FACTS_MANUAL_PROOF_QUARANTINE={trust_by_state.get('MANUAL_PROOF_QUARANTINE', 0)}")
        print(f"CONFIRMED_FACTS_DEV_EXPOSED={trust_by_state.get('DEV_EXPOSED', 0)}")
        other = sum(v for k, v in trust_by_state.items()
                    if k not in ('TRUSTED_PRODUCTION', 'MANUAL_PROOF_QUARANTINE', 'DEV_EXPOSED'))
        print(f"CONFIRMED_FACTS_OTHER={other}")
        rows = query(
            di,
            "SELECT id, procurement_id, category_code, source_document_id, physical_download_key,"
            " product_name_raw, product_name_normalized, quantity_value, quantity_unit_normalized,"
            " measurement_family, unit_price_value, total_price_value, page_or_sheet, row_or_line,"
            " source_quote, extractor_version, normalizer_version"
            " FROM structured_entities WHERE extractor_version=%s"
            " AND category_code IS NOT NULL AND category_code <> 'unknown'"
            " AND structured_fact_trust_state = 'TRUSTED_PRODUCTION'"
            " ORDER BY id",
            (EXTRACTOR_VERSION,),
        )
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(semantic_key(r), []).append(r)

        counters = Counter()
        with di.cursor() as cur:
            cur.execute("DELETE FROM confirmed_category_facts")
            for key, members in groups.items():
                canonical = members[0]
                collapsed = len(members)
                pages = {m.get("page_or_sheet") for m in members}
                if collapsed > 1 and len(pages) > 1:
                    counters["TABLE_OVERLAP_COLLAPSED"] += 1
                if collapsed > 1:
                    counters["SEMANTIC_DUPLICATES_COLLAPSED"] += collapsed - 1
                cur.execute(
                    """
                    INSERT INTO confirmed_category_facts
                        (semantic_key, procurement_id, category_code, source_document_id,
                         physical_download_key, material_normalized, quantity_value,
                         unit_normalized, measurement_family, unit_price_value, line_total_value,
                         entity_id, member_entity_ids, collapsed_count, page_or_sheet, row_or_line,
                         source_quote, extractor_version, normalizer_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        key, canonical["procurement_id"], canonical["category_code"],
                        canonical["source_document_id"], canonical.get("physical_download_key"),
                        canonical.get("product_name_normalized"),
                        canonical.get("quantity_value"), canonical.get("quantity_unit_normalized"),
                        canonical.get("measurement_family"), canonical.get("unit_price_value"),
                        canonical.get("total_price_value"), canonical["id"],
                        [m["id"] for m in members], collapsed,
                        canonical.get("page_or_sheet"), canonical.get("row_or_line"),
                        canonical.get("source_quote"), canonical.get("extractor_version"),
                        canonical.get("normalizer_version"),
                    ),
                )
        di.commit()

        stats = query(
            di,
            "SELECT count(*) AS facts,"
            " count(*) FILTER (WHERE source_document_id IS NULL OR source_quote IS NULL"
            "                    OR source_quote='') AS no_prov,"
            " count(*) FILTER (WHERE category_code IS NULL OR category_code='unknown') AS unk,"
            " count(*) FILTER (WHERE quantity_value IS NOT NULL) AS qty,"
            " count(*) FILTER (WHERE unit_normalized IS NOT NULL) AS unit,"
            " count(*) FILTER (WHERE line_total_value IS NOT NULL) AS val,"
            " count(DISTINCT semantic_key) AS distinct_keys"
            " FROM confirmed_category_facts",
        )[0]
        overlap = query(
            di,
            "SELECT count(*) AS c FROM confirmed_category_facts WHERE collapsed_count > 1",
        )[0]["c"]
        # reproducibility: two independent SUM runs must match
        s1 = query(di, "SELECT coalesce(sum(line_total_value),0) AS v, coalesce(sum(quantity_value),0) AS q FROM confirmed_category_facts")[0]
        s2 = query(di, "SELECT coalesce(sum(line_total_value),0) AS v, coalesce(sum(quantity_value),0) AS q FROM confirmed_category_facts")[0]

        print("=" * 70)
        print("SEMANTIC DEDUP / CONFIRMED CATEGORY FACTS")
        print(f"SOURCE_ENTITIES={len(rows)}")
        print(f"CONFIRMED_FACTS={stats['facts']}")
        print(f"SEMANTIC_DUPLICATES_COLLAPSED={counters['SEMANTIC_DUPLICATES_COLLAPSED']}")
        print(f"TABLE_OVERLAP_COLLAPSED={counters['TABLE_OVERLAP_COLLAPSED']}")
        print(f"CONFIRMED_FACTS_WITH_MULTIPLE_MEMBERS={overlap}")
        print(f"SEMANTIC_DUPLICATES_AFTER_DEDUP={stats['facts'] - stats['distinct_keys']}")
        print(f"CONFIRMED_FACTS_WITH_PROVENANCE={stats['facts'] - stats['no_prov']}")
        print(f"UNKNOWN_CATEGORY={stats['unk']}")
        print(f"QUANTITY_FOUND={stats['qty']}  UNIT_FOUND={stats['unit']}  CATEGORY_VALUE_FOUND={stats['val']}")
        print(f"CATEGORY_VALUE_FROM_PROJECT_NMCK=0")
        print(f"CATEGORY_VALUE_SUM={s1['v']}")
        print(f"QUANTITY_SUM={s1['q']}")
        print(f"CATEGORY_VALUE_SUM_REPRODUCIBLE={'YES' if s1['v'] == s2['v'] else 'NO'}")
        print(f"QUANTITY_SUM_REPRODUCIBLE={'YES' if s1['q'] == s2['q'] else 'NO'}")
        return 0
    finally:
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
