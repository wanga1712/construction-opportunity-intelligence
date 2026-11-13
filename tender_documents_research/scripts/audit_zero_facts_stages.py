#!/usr/bin/env python3
"""Read-only stage audit for procurements reported as NO_FACTS."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from document_processor.parse_extractors import _connect, _persist_embedded
from document_processor.parse_utils import parse_file_with_meta
from document_processor.parser_factory import ParserFactory


def _pids(value: str) -> list[int]:
    return sorted({int(item) for item in value.split(",") if item.strip()})


def _load_documents(di, pids: list[int]) -> dict[int, list[dict[str, Any]]]:
    with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT o.procurement_id, o.source_document_id, o.category_code,
                   o.track, f.file_name, f.local_path, f.local_deleted_at
              FROM document_extraction_outcomes o
              JOIN document_files f ON f.id=o.source_document_id
             WHERE o.procurement_id = ANY(%s)
             ORDER BY o.procurement_id, o.source_document_id, o.category_code
            """,
            (pids,),
        )
        grouped: dict[int, dict[int, list[dict[str, Any]]]] = {}
        for row in cur.fetchall():
            pid = int(row["procurement_id"])
            document_id = int(row["source_document_id"])
            grouped.setdefault(pid, {}).setdefault(document_id, []).append(dict(row))
    return {
        pid: [items[0] | {"contexts": items} for items in documents.values()]
        for pid, documents in grouped.items()
    }


def _load_normalization_state(
    di, pids: list[int]
) -> dict[int, dict[str, Any]]:
    with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT procurement_id, status, attempt_count,
                   requested_at, completed_at, last_error
              FROM post_parse_category_jobs
             WHERE procurement_id = ANY(%s)
            """,
            (pids,),
        )
        jobs = {int(row["procurement_id"]): dict(row) for row in cur.fetchall()}
        cur.execute(
            """
            SELECT r.procurement_id, count(DISTINCT r.id) AS rows,
                   count(DISTINCT r.id) FILTER (
                     WHERE r.category_code IS NOT NULL
                   ) AS categorized,
                   count(DISTINCT d.estimate_row_id) AS attempted
              FROM structured_estimate_rows r
              LEFT JOIN structured_estimate_row_category_decisions d
                ON d.estimate_row_id=r.id
             WHERE r.procurement_id = ANY(%s)
             GROUP BY r.procurement_id
            """,
            (pids,),
        )
        rows = {int(row["procurement_id"]): dict(row) for row in cur.fetchall()}
    return {
        pid: {**(rows.get(pid) or {}), "job": jobs.get(pid)}
        for pid in pids
    }


def _parse_document(path: Path) -> tuple[str, Any, str]:
    if not path.is_file():
        return "", None, "FILE_NOT_LOCAL"
    parser = ParserFactory().get_parser(path)
    if parser is None:
        return "", None, "UNSUPPORTED_FORMAT"
    try:
        text, line_meta = parse_file_with_meta(parser, path)
    except Exception as exc:  # noqa: BLE001 - audit must continue
        return "", None, f"PARSE_ERROR:{type(exc).__name__}"
    return text or "", line_meta, "PARSED" if text else "EMPTY_TEXT"


def _evaluate_document(
    document: dict[str, Any], allowed_categories: set[str]
) -> dict[str, Any]:
    path = Path(str(document.get("local_path") or ""))
    text, line_meta, parse_status = _parse_document(path)
    if parse_status in {"FILE_NOT_LOCAL", "UNSUPPORTED_FORMAT"}:
        return {
            "parse_status": parse_status,
            "raw_extracted": None,
            "goods_accepted": None,
            "category_resolved": None,
            "allowed_rejected": None,
            "persisted_created": 0,
            "persisted_reused": 0,
            "error": None,
        }
    contexts = document.get("contexts") or [document]
    best = None
    for context in contexts:
        track = str(context.get("track") or "EMBEDDED")
        category = str(context.get("category_code") or "")
        result = _persist_embedded(
            None,
            path,
            text,
            line_meta,
            int(document["procurement_id"]),
            str(document.get("file_name") or path.name),
            category,
            int(document["source_document_id"]),
            str(path),
            track,
            None,
            allowed_categories,
            persist=False,
        )
        candidate = {
            "parse_status": parse_status,
            "raw_extracted": result.extracted_facts,
            "goods_accepted": result.goods_accepted_facts,
            "category_resolved": result.category_resolved_facts,
            "allowed_rejected": result.allowed_rejected_facts,
            "persisted_created": result.created,
            "persisted_reused": result.reused,
            "error": result.error,
        }
        if best is None or (candidate["raw_extracted"] or 0) > (
            best["raw_extracted"] or 0
        ):
            best = candidate
    return best or {
        "parse_status": parse_status,
        "raw_extracted": 0,
        "goods_accepted": 0,
        "category_resolved": 0,
        "allowed_rejected": 0,
        "persisted_created": 0,
        "persisted_reused": 0,
        "error": None,
    }


def _classify(card: dict[str, Any]) -> str:
    if not card["full_normalization_attempted"]:
        return "Z6_FULL_NORMALIZATION_NOT_ATTEMPTED"
    if card["raw_extracted_fact_count"] == 0:
        return "Z1_RAW_EXTRACTOR_FOUND_NOTHING"
    if card["goods_gate_accepted_count"] == 0:
        return "Z2_RAW_FACTS_FOUND_BUT_GOODS_GATE_REJECTED_ALL"
    if card["category_resolved_count"] == 0:
        return "Z3_GOODS_ACCEPTED_BUT_CATEGORY_RESOLUTION_REJECTED_ALL"
    if card["persist_created_count"] == 0 and card["persist_reused_count"] > 0:
        return "Z4_FACTS_PERSISTED_AS_REUSED_ONLY"
    if card["persistence_error"]:
        return "Z5_PERSISTENCE_PROBLEM"
    if card["post_parse_normalized_count"] == 0:
        return "Z7_FULL_NORMALIZATION_ATTEMPTED_ZERO_CATEGORY_MATCH"
    return "Z8_OTHER"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--procurement-ids", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    pids = _pids(args.procurement_ids)
    di = _connect()
    try:
        documents = _load_documents(di, pids)
        normalization = _load_normalization_state(di, pids)
        cards = []
        for pid in pids:
            docs = documents.get(pid) or []
            allowed = {
                str(context.get("category_code"))
                for doc in docs
                for context in doc.get("contexts") or []
                if context.get("category_code")
            }
            evaluated = [_evaluate_document(doc, allowed) for doc in docs]
            known = [
                item
                for item in evaluated
                if item.get("raw_extracted") is not None
            ]
            state = normalization.get(pid) or {}
            job = state.get("job")
            attempted_rows = int(state.get("attempted") or 0)
            full_attempted = bool(job) or attempted_rows > 0
            card = {
                "procurement_id": pid,
                "material_document_count": len(docs),
                "local_document_count": sum(
                    item["parse_status"] not in {
                        "FILE_NOT_LOCAL", "UNSUPPORTED_FORMAT"
                    }
                    for item in evaluated
                ),
                "parse_attempted": any(
                    item["parse_status"] in {"PARSED", "EMPTY_TEXT", "PARSE_ERROR"}
                    for item in evaluated
                ),
                "embedded_extraction_attempted": bool(known),
                "raw_extracted_fact_count": sum(
                    int(item.get("raw_extracted") or 0) for item in known
                ),
                "goods_gate_accepted_count": sum(
                    int(item.get("goods_accepted") or 0) for item in known
                ),
                "category_resolved_count": sum(
                    int(item.get("category_resolved") or 0) for item in known
                ),
                "allowed_category_rejected_count": sum(
                    int(item.get("allowed_rejected") or 0) for item in known
                ),
                "persist_created_count": sum(
                    int(item.get("persisted_created") or 0) for item in evaluated
                ),
                "persist_reused_count": sum(
                    int(item.get("persisted_reused") or 0) for item in evaluated
                ),
                "persistence_error": next(
                    (
                        item["error"]
                        for item in evaluated
                        if item.get("error")
                    ),
                    None,
                ),
                "full_normalization_attempted": full_attempted,
                "full_normalization_version": (
                    "estimate_row_taxonomy_resolver_v1"
                    if full_attempted else None
                ),
                "full_normalization_result": job,
                "structured_estimate_rows": int(state.get("rows") or 0),
                "post_parse_normalized_count": int(state.get("categorized") or 0),
                "parse_status_counts": dict(
                    Counter(item["parse_status"] for item in evaluated)
                ),
                "documents": evaluated,
            }
            card["bucket"] = _classify(card)
            cards.append(card)
        counts = Counter(card["bucket"] for card in cards)
        result = {
            "cohort": len(cards),
            "bucket_counts": dict(sorted(counts.items())),
            "full_normalization_attempted": sum(
                card["full_normalization_attempted"] for card in cards
            ),
            "true_zero_after_full_normalization": (
                counts.get("Z7_FULL_NORMALIZATION_ATTEMPTED_ZERO_CATEGORY_MATCH", 0)
                if all(card["full_normalization_attempted"] for card in cards)
                else None
            ),
            "cards": cards,
        }
        Path(args.report).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    finally:
        di.close()
    print(json.dumps({key: value for key, value in result.items() if key != "cards"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
