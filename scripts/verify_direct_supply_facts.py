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
    SELECT se.id
      FROM structured_entities se
      JOIN structured_extraction_runs r ON r.id = se.run_id
     WHERE se.extractor_version = %s
       AND se.category_code = ANY(%s)
       AND se.structured_fact_trust_state = 'MANUAL_PROOF_QUARANTINE'
       AND coalesce(se.source_quote, '') <> ''
       AND r.source_text_snapshot IS NOT NULL
       AND position(se.source_quote in r.source_text_snapshot) > 0
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    di = psycopg2.connect(**di_dsn())
    try:
        cur = di.cursor()
        cur.execute(CANDIDATES_SQL, (EXTRACTOR_VERSION, DIRECT_CATS))
        ids = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT count(*) FROM structured_entities"
            " WHERE extractor_version=%s AND category_code = ANY(%s)"
            "   AND structured_fact_trust_state='MANUAL_PROOF_QUARANTINE'",
            (EXTRACTOR_VERSION, DIRECT_CATS),
        )
        quarantine_total = int(cur.fetchone()[0] or 0)
        print(f"DIRECT_CATEGORIES={DIRECT_CATS}")
        print(f"DIRECT_QUARANTINE_TOTAL={quarantine_total}")
        print(f"DIRECT_QUOTE_VERIFIED_TO_PROMOTE={len(ids)}")
        print(f"DIRECT_UNVERIFIED_REMAIN={quarantine_total - len(ids)}")
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
