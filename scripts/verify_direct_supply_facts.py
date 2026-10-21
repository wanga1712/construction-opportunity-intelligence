#!/usr/bin/env python3
"""Direct-supply documentary verification (promotion QUARANTINE -> TRUSTED_PRODUCTION).

Scope: DIRECT supply categories only (computers / lighting / cable_support_systems).
A quarantined fact is promoted only when its `source_quote` is literally present in
the stored run snapshot (`structured_extraction_runs.source_text_snapshot`) — i.e. the
document actually says it. Nothing is promoted "because it was extracted".

Default: dry-run. Use --apply to write.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.good_supply_facts_service import classify_supply_row  # noqa: E402

EXTRACTOR_VERSION = os.getenv("SEMANTIC_EXTRACTOR_VERSION", "EMBEDDED_EXTRACTOR_V1")
DIRECT_CATS = (
    os.getenv("DIRECT_SUPPLY_CATEGORIES", "computers,lighting,cable_support_systems")
    .split(",")
)
DIRECT_CATS = [c.strip() for c in DIRECT_CATS if c.strip()]


def di_dsn():
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


CANDIDATES_SQL = """
    SELECT se.id, se.category_code, se.source_document_id, se.entity_type,
           se.product_name_raw, se.product_name_normalized,
           se.quantity_value, se.quantity_unit_normalized,
           se.total_price_value, se.source_quote,
           r.source_text_snapshot
      FROM structured_entities se
      JOIN structured_extraction_runs r ON r.id = se.run_id
     WHERE se.extractor_version = %s
       AND se.category_code = ANY(%s)
       AND se.structured_fact_trust_state = 'MANUAL_PROOF_QUARANTINE'
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    di = psycopg2.connect(**di_dsn())
    try:
        cur = di.cursor()
        cur.execute(CANDIDATES_SQL, (EXTRACTOR_VERSION, DIRECT_CATS))
        candidates = cur.fetchall()
        goods = []
        verified_keys = set()
        for row in candidates:
            (
                entity_id, category_code, source_document_id, entity_type,
                name_raw, name_norm, quantity, unit, total, quote, snapshot,
            ) = row
            payload = {
                "category_code": category_code,
                "entity_type": entity_type,
                "product_name_raw": name_raw,
                "product_name_normalized": name_norm,
                "quantity_value": quantity,
                "quantity_unit_normalized": unit,
                "total_price_value": total,
                "source_quote": quote,
            }
            if classify_supply_row(payload) is not None:
                continue
            verified = bool(
                quote and snapshot is not None and str(quote) in str(snapshot)
            )
            semantic_key = (
                str(category_code),
                str(source_document_id),
                str(name_norm or name_raw or "").strip().lower(),
                round(float(quantity), 9),
                str(unit or "").upper(),
                round(float(total), 2),
            )
            goods.append(
                {
                    "id": int(entity_id),
                    "category": str(category_code),
                    "verified": verified,
                    "semantic_key": semantic_key,
                }
            )
            if verified:
                verified_keys.add(semantic_key)

        ids = [item["id"] for item in goods if item["verified"]]
        stale_ids = [
            item["id"]
            for item in goods
            if not item["verified"] and item["semantic_key"] in verified_keys
        ]
        actionable_unverified = [
            item
            for item in goods
            if not item["verified"] and item["semantic_key"] not in verified_keys
        ]
        by_category = {}
        for item in goods:
            stats = by_category.setdefault(item["category"], {
                "goods": 0, "verified": 0, "stale": 0, "unverified": 0
            })
            stats["goods"] += 1
            if item["verified"]:
                stats["verified"] += 1
            elif item["id"] in stale_ids:
                stats["stale"] += 1
            else:
                stats["unverified"] += 1
        cur.execute(
            "SELECT count(*) FROM structured_entities"
            " WHERE extractor_version=%s AND category_code = ANY(%s)"
            "   AND structured_fact_trust_state='MANUAL_PROOF_QUARANTINE'",
            (EXTRACTOR_VERSION, DIRECT_CATS),
        )
        quarantine_total = int(cur.fetchone()[0] or 0)
        print(f"DIRECT_CATEGORIES={DIRECT_CATS}")
        print(f"DIRECT_QUARANTINE_TOTAL={quarantine_total}")
        print(f"DIRECT_GOODS_CANDIDATES={len(goods)}")
        print(f"DIRECT_NON_GOODS_OR_INCOMPLETE={quarantine_total - len(goods)}")
        print(f"DIRECT_QUOTE_VERIFIED_TO_PROMOTE={len(ids)}")
        print(f"DIRECT_RAW_UNVERIFIED={len(goods) - len(ids)}")
        print(f"DIRECT_STALE_SUPERSEDED={len(stale_ids)}")
        print(f"DIRECT_GOODS_CANDIDATES_UNVERIFIED={len(actionable_unverified)}")
        for category in sorted(by_category):
            stats = by_category[category]
            print(
                f"CATEGORY {category}: goods={stats['goods']}"
                f" verified={stats['verified']} stale={stats['stale']}"
                f" unverified={stats['unverified']}"
            )
        if not args.apply:
            print("DRY_RUN=YES (no writes)")
            return 0
        cur.execute(
            "UPDATE structured_entities SET structured_fact_trust_state='TRUSTED_PRODUCTION'"
            " WHERE id = ANY(%s)",
            (ids,),
        )
        promoted = cur.rowcount
        di.commit()
        cur.execute(
            "SELECT structured_fact_trust_state, count(*) FROM structured_entities"
            " WHERE extractor_version=%s AND category_code = ANY(%s) GROUP BY 1",
            (EXTRACTOR_VERSION, DIRECT_CATS),
        )
        print(f"DIRECT_PROMOTED={promoted}")
        for state, n in cur.fetchall():
            print(f"STATE {state}={n}")
        return 0
    finally:
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
