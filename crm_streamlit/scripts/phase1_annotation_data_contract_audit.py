#!/usr/bin/env python3
"""Read-only real-data probe for annotation card Phase 1.

No document downloads, DDL, writes, model calls, or pipeline actions.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit"))
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89")]

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.annotation_card_provenance import load_annotation_history, source_law
from src.services.commercial_routing_v3.document_links import _s7_dsn, resolve_document_links
from src.services.db_bootstrap import connect_databases

BASELINE = "149e5d9bf25d9164967e5ccd8abba3cade2e18b3"
PROCUREMENT_IDS = [8021, 17390, 20254, 20256, 1013]


def serial(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def crm_rows(db: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    return [dict(row) for row in (db.execute_query(sql, params) or [])]


def source_metadata_and_row(proc: dict) -> dict:
    table = proc["source_table"]
    allowed = {
        "id", "contract_number", "purchase_number", "registry_number", "name", "subject",
        "customer_name", "customer_inn", "region", "address", "initial_price", "price",
        "final_price", "contract_price", "start_date", "end_date", "award_date",
        "contract_date", "execution_start_date", "execution_end_date", "published_at",
        "publication_date", "url", "href", "tender_url", "purchase_url", "contract_url",
        "contract_href", "contract_link", "source_url", "updated_at", "created_at",
    }
    conn = psycopg2.connect(**_s7_dsn())
    try:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (table,),
            )
            columns = [dict(row) for row in (cur.fetchall() or [])]
            names = {row["column_name"] for row in columns}
            selected = sorted(names & allowed)
            contract_url_columns = sorted(
                name for name in names
                if "contract" in name.lower() and any(token in name.lower() for token in ("url", "link", "href"))
            )
            selected = sorted(set(selected) | set(contract_url_columns))
            row = None
            if selected:
                where_col = "contract_number" if "contract_number" in names else "id"
                where_val = proc["contract_number"] if where_col == "contract_number" else proc["source_id"]
                cur.execute(
                    f"SELECT {', '.join(selected)} FROM {table} WHERE {where_col}=%s ORDER BY id DESC NULLS LAST LIMIT 1",
                    (where_val,),
                )
                fetched = cur.fetchone()
                row = dict(fetched) if fetched else None
        conn.rollback()
    finally:
        conn.close()
    factual_contract_urls = {
        name: row.get(name) for name in contract_url_columns if row and row.get(name)
    }
    return {
        "column_inventory": columns,
        "selected_source_facts": row,
        "contract_url_columns": contract_url_columns,
        "factual_contract_urls": factual_contract_urls,
    }


def joined_documents(documents: list[dict], observations: list[dict]) -> dict:
    by_id: dict[str, list[dict]] = {}
    by_url: dict[str, list[dict]] = {}
    for obs in observations:
        if obs.get("source_document_id"):
            by_id.setdefault(str(obs["source_document_id"]), []).append(obs)
        if obs.get("source_document_url"):
            by_url.setdefault(str(obs["source_document_url"]), []).append(obs)
    rows = []
    used_observation_ids: set[int] = set()
    for doc in documents:
        id_hits = by_id.get(str(doc.get("source_document_id")), []) if doc.get("source_document_id") is not None else []
        url_hits = by_url.get(str(doc.get("document_url")), []) if doc.get("document_url") else []
        hits = id_hits or url_hits
        method = "source_document_id" if id_hits else ("source_document_url" if url_hits else None)
        used_observation_ids.update(int(row["id"]) for row in hits)
        if not hits:
            state = "UNOBSERVED"
        elif any(row.get("download_status") not in (None, "SUCCESS", "DOWNLOADED") for row in hits):
            state = "DOWNLOAD_OR_PARSE_FAILED"
        elif any(row.get("commercial_evidence_found") for row in hits):
            state = "OBSERVED_WITH_EVIDENCE"
        else:
            state = "OBSERVED_NO_EVIDENCE"
        rows.append({"source_document": doc, "observations": hits, "join_method": method, "state": state})
    orphans = [row for row in observations if int(row["id"]) not in used_observation_ids]
    return {"rows": rows, "orphan_observations": orphans}


def main() -> int:
    _, _, crm_db, _ = connect_databases()
    placeholders = ",".join(["%s"] * len(PROCUREMENT_IDS))
    procurements = crm_rows(
        crm_db,
        f"""
        SELECT id, source_table, source_id, contract_number, auction_name, customer,
               delivery_region, initial_price, final_price, final_contract_price,
               start_date, end_date, delivery_start_date, delivery_end_date,
               award_date, contract_signed_at, execution_start_at, execution_end_at,
               tender_link, crm_stage, award_status, crm_created_at, crm_updated_at,
               source_updated_at
        FROM crm_procurements WHERE id IN ({placeholders}) ORDER BY id
        """,
        tuple(PROCUREMENT_IDS),
    )
    canonical = {
        int(row["procurement_id"]): dict(row)
        for row in crm_rows(
            crm_db,
            f"SELECT procurement_id, card_json, card_version, built_at, updated_at "
            f"FROM crm_v3_canonical_procurement_cards WHERE procurement_id IN ({placeholders})",
            tuple(PROCUREMENT_IDS),
        )
    }
    global_observation_count = crm_rows(
        crm_db, "SELECT count(*) AS rows, count(DISTINCT procurement_id) AS procurements FROM crm_v3_document_observations"
    )[0]
    results = []
    for proc in procurements:
        pid = int(proc["id"])
        resolved = resolve_document_links(
            source_table=proc["source_table"], source_id=proc["source_id"],
            contract_number=proc["contract_number"], limit=10000,
        )
        observations = crm_rows(
            crm_db,
            "SELECT * FROM crm_v3_document_observations WHERE procurement_id=%s ORDER BY observed_at,id",
            (pid,),
        )
        joined = joined_documents(resolved.get("links") or [], observations)
        history = load_annotation_history(crm_db, pid, proc)
        signatures = Counter(
            (str(event.get("at")), event.get("title"), event.get("detail"), event.get("authority"))
            for event in history
        )
        card = (canonical.get(pid) or {}).get("card_json") or {}
        results.append({
            "procurement": proc,
            "law": source_law(proc["source_table"]),
            "canonical_card_metadata": {k: v for k, v in (canonical.get(pid) or {}).items() if k != "card_json"},
            "canonical_only_facts": {k: card.get(k) for k in (
                "normalized_lifecycle", "published_at", "submission_start_at", "submission_deadline_at",
                "contract_signed_at", "execution_start_at", "execution_end_at", "award_at",
                "document_link_count", "raw_document_link_count", "unique_document_url_count",
                "unique_physical_download_target_count", "duplicate_physical_download_targets",
                "document_links_summary", "source_origin", "deadline_pressure",
            ) if card.get(k) is not None},
            "source": source_metadata_and_row(proc),
            "document_resolution": {k: v for k, v in resolved.items() if k != "links"},
            "documents": resolved.get("links") or [],
            "observation_count": len(observations),
            "joined_documents": joined,
            "history": history,
            "history_event_count": len(history),
            "duplicate_history_events": sum(count - 1 for count in signatures.values() if count > 1),
        })
    out = {
        "baseline_commit": BASELINE,
        "audit_mode": "READ_ONLY",
        "production_runtime_ref_observed": os.environ.get("PHASE1_RUNTIME_REF"),
        "global_document_observations": global_observation_count,
        "awarded_223_available_in_crm": False,
        "procurements": results,
    }
    print(json.dumps(serial(out), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
