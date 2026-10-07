#!/usr/bin/env python3
"""Universal procurement opportunity classifier daemon.

This daemon does NOT download documents.  It consumes already available
procurement metadata, parsed matches/product previews and the existing object
AI classification, then writes:

  * crm_procurement_classifications
  * crm_procurement_opportunities
  * crm_product_taxonomy_discovery (+ auto-promotion)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from loguru import logger  # noqa: E402

from src.services import procurement_opportunity_store as store  # noqa: E402
from src.services.db_bootstrap import connect_databases  # noqa: E402
from src.services.docs_match_preview import load_match_previews  # noqa: E402
from src.services.procurement_opportunity_ai import (  # noqa: E402
    DEFAULT_MODEL,
    MODEL_VERSION,
    classify_procurement,
)


def _source_hash(
    row: Dict[str, Any],
    preview: Dict[str, Any],
    object_ai: Dict[str, Any],
) -> str:
    payload = {
        "title": row.get("auction_name"),
        "okpd_code": row.get("okpd_code"),
        "okpd_name": row.get("okpd_name"),
        "initial_price": str(row.get("initial_price") or ""),
        "customer": row.get("customer"),
        "registry_type": row.get("source_table"),
        "matched_products": sorted(
            preview.get("matched_products_ai")
            or preview.get("matched_product_preview")
            or []
        ),
        "document_evidence": sorted(preview.get("docs_evidence_preview") or []),
        "object_ai": {
            "primary_class": object_ai.get("primary_class"),
            "subcategory": object_ai.get("subcategory"),
            "object_type": object_ai.get("object_type"),
            "object_subtype": object_ai.get("object_subtype"),
            "work_type": object_ai.get("work_type"),
            "confidence": object_ai.get("classification_confidence"),
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_context(
    row: Dict[str, Any],
    preview: Dict[str, Any],
    object_ai: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "title": row.get("auction_name"),
        "contract_number": row.get("contract_number"),
        "okpd_code": row.get("okpd_code"),
        "okpd_name": row.get("okpd_name"),
        "initial_price": row.get("initial_price"),
        "customer": row.get("customer"),
        "registry_type": row.get("source_table"),
        "source_table": row.get("source_table"),
        "matched_products": preview.get("matched_products_ai")
        or preview.get("matched_product_preview")
        or [],
        "document_evidence": preview.get("docs_evidence_preview") or [],
        "existing_object_classification": object_ai,
    }


def _has_enough_context(context: Dict[str, Any]) -> bool:
    return bool(
        str(context.get("title") or "").strip()
        or str(context.get("okpd_code") or "").strip()
        or str(context.get("okpd_name") or "").strip()
        or context.get("matched_products")
        or context.get("document_evidence")
    )


def _print_smoke(result: Dict[str, Any]) -> None:
    opportunities = result.get("opportunities") or []
    if not opportunities:
        print(
            " | ".join(
                [
                    str(result.get("procurement_mode") or ""),
                    "",
                    "",
                    str(result.get("object_present") or ""),
                    str(result.get("object_type") or ""),
                    str(result.get("taxonomy_action") or ""),
                ]
            )
        )
        return
    for opportunity in opportunities:
        print(
            " | ".join(
                [
                    str(result.get("procurement_mode") or ""),
                    str(opportunity.get("category_code") or ""),
                    str(opportunity.get("subcategory_code") or ""),
                    str(result.get("object_present") or ""),
                    str(result.get("object_type") or ""),
                    str(opportunity.get("taxonomy_action") or ""),
                ]
            )
        )


def process_batch(
    tender_db: Any,
    crm_db: Any,
    limit: int,
) -> Dict[str, Any]:
    try:
        taxonomy = store.load_active_taxonomy(crm_db)
    except Exception as exc:
        logger.warning(f"active taxonomy load failed: {exc}")
        taxonomy = []

    existing_hashes = store.load_classification_hashes(crm_db)
    rows = store.load_pending_procurements(crm_db, limit)

    stats = {
        "loaded": len(rows),
        "skipped_same_hash": 0,
        "ready": 0,
        "needs_documents": 0,
        "error": 0,
        "opportunities": 0,
        "promoted": [],
    }
    smoke_rows: List[Dict[str, Any]] = []

    for row in rows:
        tender_id = row.get("source_id")
        registry_type = str(row.get("source_table") or "")
        object_key = store.make_object_key(registry_type, tender_id)
        preview = {}
        if tender_id and registry_type:
            try:
                preview = load_match_previews(
                    tender_db,
                    [(int(tender_id), registry_type)],
                ).get((int(tender_id), registry_type), {})
            except Exception as exc:
                logger.warning(f"match preview load failed {object_key}: {exc}")

        try:
            object_ai = store.load_existing_object_ai(
                crm_db, object_key, tender_id, registry_type
            )
        except Exception as exc:
            logger.warning(f"object AI load failed {object_key}: {exc}")
            object_ai = {}

        source_hash = _source_hash(row, preview, object_ai)
        if existing_hashes.get(object_key) == source_hash:
            stats["skipped_same_hash"] += 1
            continue

        context = _build_context(row, preview, object_ai)
        if not _has_enough_context(context):
            store.save_classification(
                crm_db,
                object_key=object_key,
                tender_id=tender_id,
                registry_type=registry_type,
                procurement_mode="unknown",
                object_present=False,
                object_payload={},
                classification_status="needs_documents",
                classification_confidence=0.0,
                source_hash=source_hash,
                model_name=None,
                model_version=None,
            )
            stats["needs_documents"] += 1
            smoke_rows.append(
                {
                    "procurement_mode": "unknown",
                    "object_present": False,
                    "object_type": None,
                    "taxonomy_action": None,
                    "opportunities": [],
                }
            )
            continue

        try:
            result = classify_procurement(context, taxonomy, timeout=90)
        except Exception as exc:
            logger.exception(f"classification failed {object_key}: {exc}")
            store.save_classification(
                crm_db,
                object_key=object_key,
                tender_id=tender_id,
                registry_type=registry_type,
                procurement_mode="unknown",
                object_present=False,
                object_payload={},
                classification_status="error",
                classification_confidence=0.0,
                source_hash=source_hash,
                model_name=os.getenv("PROCUREMENT_OPPORTUNITY_MODEL", DEFAULT_MODEL),
                model_version=MODEL_VERSION,
            )
            stats["error"] += 1
            continue

        mode = str(result.get("procurement_mode") or "unknown")
        object_present = bool(result.get("object_present"))
        object_payload = result.get("object") or {}
        opportunities = result.get("opportunities") or []
        classification_status = (
            "needs_documents" if mode == "unknown" and not opportunities else "ready"
        )
        confidence = float(result.get("classification_confidence") or 0.0)

        model_name = os.getenv("PROCUREMENT_OPPORTUNITY_MODEL", DEFAULT_MODEL)
        store.save_classification(
            crm_db,
            object_key=object_key,
            tender_id=tender_id,
            registry_type=registry_type,
            procurement_mode=mode,
            object_present=object_present,
            object_payload=object_payload,
            classification_status=classification_status,
            classification_confidence=confidence,
            source_hash=source_hash,
            model_name=model_name,
            model_version=MODEL_VERSION,
        )

        old_signatures = store.load_opportunity_signatures(crm_db, object_key)
        store.replace_opportunities(
            crm_db,
            object_key=object_key,
            tender_id=tender_id,
            registry_type=registry_type,
            procurement_mode=mode,
            opportunities=opportunities,
            model_name=model_name,
            model_version=MODEL_VERSION,
        )

        for opportunity in opportunities:
            if opportunity.get("taxonomy_action") != "propose_new":
                continue
            signature = (
                str(opportunity.get("category_code") or ""),
                str(opportunity.get("subcategory_code") or ""),
            )
            store.record_discovery(
                crm_db,
                parent_name=str(opportunity.get("category_name") or ""),
                subcategory_name=str(opportunity.get("subcategory_name") or ""),
                sample_product_name=str(opportunity.get("product_name") or ""),
                confidence=float(opportunity.get("confidence") or 0.0),
                total_amount=float(row.get("initial_price") or 0.0),
                is_new_procurement=signature not in old_signatures,
            )

        promoted = store.promote_discovery(crm_db)
        if promoted:
            stats["promoted"].extend(promoted)

        stats["opportunities"] += len(opportunities)
        stats["ready" if classification_status == "ready" else "needs_documents"] += 1
        smoke_rows.append(
            {
                "procurement_mode": mode,
                "object_present": object_present,
                "object_type": object_payload.get("object_type"),
                "taxonomy_action": opportunities[0].get("taxonomy_action")
                if opportunities
                else None,
                "opportunities": opportunities,
            }
        )

    return {"stats": stats, "rows": smoke_rows}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Universal procurement opportunity classifier"
    )
    parser.add_argument("--once", action="store_true", help="run one batch and exit")
    parser.add_argument(
        "--loop", action="store_true", help="run continuously until interrupted"
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()

    _radar, tender_db, crm_db, warn = connect_databases()
    if not crm_db:
        print("CRM_DB_UNAVAILABLE" + (f" | {warn}" if warn else ""))
        return 2
    if not store.ensure_schema(crm_db):
        print(
            "SCHEMA_NOT_READY: apply "
            "src/migrations/procurement_opportunity_classifier_1.sql"
        )
        return 3

    while True:
        outcome = process_batch(tender_db, crm_db, args.limit)
        stats = outcome["stats"]
        print(
            " | ".join(
                [
                    f"loaded={stats['loaded']}",
                    f"skipped={stats['skipped_same_hash']}",
                    f"ready={stats['ready']}",
                    f"needs_documents={stats['needs_documents']}",
                    f"error={stats['error']}",
                    f"opportunities={stats['opportunities']}",
                    f"promoted={len(stats['promoted'])}",
                ]
            )
        )
        for row in outcome["rows"]:
            _print_smoke(row)
        if args.once or not args.loop:
            break
        time.sleep(max(1, int(args.interval)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
