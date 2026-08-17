"""Bridge: live processing results for procurement cards (CRM-BRIDGE-1).

Two batch queries per render cycle (zero N+1):
  1. document_processing_queue  — via (contract_reg_number, table_source)
     → queue status, predicted_gold_prob, commercial_scale_score
  2. tender_document_matches + details — via tender_id = source_id
     → match_count, evidence_count, product_names, last_processed_at

Gold audit result (read-only):
  - document_processing_queue.predicted_gold_prob  max=0.23 (priority model input, not quality)
  - document_processing_queue.commercial_scale_score 75-100 (commercial scale, not match quality)
  - Neither field is the match-quality score needed for medals.
  - Writer for match quality: does not yet exist → tracked as MEDAL-ENGINE-1.
  - Full Gold medal requires MEDAL-ENGINE-1 to write commercial_score to crm_procurements.
  - This bridge shows queue/evidence data as informational display only.
"""
from __future__ import annotations

from typing import Optional

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

_GOLD_PROB_THRESHOLD = 0.60  # model max is ~0.23; no cards reach this in current data


def _tm_conn():
    import psycopg2
    kwargs = dict(require_crm_db_connect_kwargs())
    # This bridge queries tender_monitor tables; original production code
    # used CRM_DB_* identity with dbname hardcoded to tender_monitor.
    kwargs["dbname"] = "tender_monitor"
    kwargs["connect_timeout"] = 5
    return psycopg2.connect(**kwargs)


def load_batch(cards: list[dict]) -> dict[int, dict]:
    """Return {crm_procurement_id: proc_dict}.

    proc_dict keys:
      queue_status, queue_created_at,
      predicted_gold_prob, commercial_scale_score, category_confidence,
      match_count, interesting_count, evidence_count,
      last_processed_at, product_names,
      has_results, is_gold_candidate
    """
    if not cards:
        return {}

    # Index by (contract_number, source_table) → crm_id
    by_queue_key: dict[tuple[str, str], int] = {}
    # Index by source_id → crm_id
    by_source_id: dict[int, int] = {}

    for c in cards:
        crm_id = c.get("id")
        if not crm_id:
            continue
        cn = c.get("contract_number")
        src_table = c.get("source_table")
        src_id = c.get("source_id")
        if cn and src_table:
            by_queue_key[(cn, src_table)] = crm_id
        if src_id is not None:
            by_source_id[int(src_id)] = crm_id

    results: dict[int, dict] = {c["id"]: {} for c in cards if c.get("id")}

    if not by_queue_key and not by_source_id:
        return _finalize(results)

    try:
        from psycopg2.extras import RealDictCursor
        conn = _tm_conn()
        try:
            # ── Query 1: queue status + Gold scores ────────────────────────────
            if by_queue_key:
                cns    = [k[0] for k in by_queue_key]
                tables = [k[1] for k in by_queue_key]
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT DISTINCT ON (contract_reg_number, table_source)
                            contract_reg_number,
                            table_source,
                            status,
                            created_at,
                            predicted_gold_prob,
                            commercial_scale_score,
                            category_confidence
                        FROM document_processing_queue
                        WHERE (contract_reg_number, table_source) IN
                              (SELECT * FROM UNNEST(%s::text[], %s::text[]))
                        ORDER BY contract_reg_number, table_source, id DESC
                    """, (cns, tables))
                    for row in cur.fetchall():
                        key = (row["contract_reg_number"], row["table_source"])
                        crm_id = by_queue_key.get(key)
                        if crm_id is not None:
                            results[crm_id].update({
                                "queue_status":          row["status"],
                                "queue_created_at":      row["created_at"],
                                "predicted_gold_prob":   (
                                    float(row["predicted_gold_prob"])
                                    if row["predicted_gold_prob"] is not None else None
                                ),
                                "commercial_scale_score": (
                                    float(row["commercial_scale_score"])
                                    if row["commercial_scale_score"] is not None else None
                                ),
                                "category_confidence": (
                                    float(row["category_confidence"])
                                    if row["category_confidence"] is not None else None
                                ),
                            })

            # ── Query 2: matches + evidence ────────────────────────────────────
            if by_source_id:
                source_ids = list(by_source_id.keys())
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT
                            m.tender_id,
                            COUNT(DISTINCT m.id)                              AS match_count,
                            COUNT(DISTINCT CASE WHEN m.is_interesting
                                               THEN m.id END)                 AS interesting_count,
                            COUNT(d.id)                                       AS evidence_count,
                            MAX(m.processed_at)                               AS last_processed_at,
                            ARRAY_AGG(DISTINCT d.product_name
                                      ORDER BY d.product_name)
                                FILTER (WHERE d.product_name IS NOT NULL
                                          AND d.product_name <> '')           AS product_names
                        FROM tender_document_matches m
                        LEFT JOIN tender_document_match_details d
                               ON d.match_id = m.id
                        WHERE m.tender_id = ANY(%s)
                        GROUP BY m.tender_id
                    """, (source_ids,))
                    for row in cur.fetchall():
                        crm_id = by_source_id.get(row["tender_id"])
                        if crm_id is not None:
                            results[crm_id].update({
                                "match_count":       int(row["match_count"] or 0),
                                "interesting_count": int(row["interesting_count"] or 0),
                                "evidence_count":    int(row["evidence_count"] or 0),
                                "last_processed_at": row["last_processed_at"],
                                "product_names":     list(row["product_names"] or []),
                            })
        finally:
            conn.close()
    except Exception:
        pass

    return _finalize(results)


def _finalize(results: dict[int, dict]) -> dict[int, dict]:
    for proc in results.values():
        proc["has_results"] = bool(
            proc.get("match_count", 0) or proc.get("evidence_count", 0)
        )
        gold_prob = proc.get("predicted_gold_prob")
        proc["is_gold_candidate"] = (
            gold_prob is not None and gold_prob >= _GOLD_PROB_THRESHOLD
        )
    return results


def enrich_card(card: dict, proc: dict) -> None:
    """Inject processing results into card dict in-place.

    Sets:
      _proc         — raw proc dict (queue status, match/evidence counts, product names)
      _queue_status — backward-compat field used by _torgi_priority_score
      evidence_count — propagated for detail card display
      processing_stage — advanced to 'ai_verified' when daemon found interesting matches
                          (does NOT advance to 'ranked'; that requires MEDAL-ENGINE-1)

    Does NOT inject commercial_score or promote to 'ranked':
      commercial_scale_score in the queue is a priority scale (0-100),
      not a match-quality score. Medals require crm_procurements.commercial_score
      which is written by MEDAL-ENGINE-1 (not yet implemented).
    """
    card["_proc"] = proc
    card["_queue_status"] = proc.get("queue_status")

    # Advance processing_stage to 'ai_verified' when daemon confirmed interesting matches.
    # This is informational: shows documents were analyzed, but medal not yet calculated.
    if proc.get("interesting_count", 0) > 0 and proc.get("queue_status") in (
        "completed", "processing"
    ):
        if card.get("processing_stage", "matches_found") in (
            "raw", "documents_loaded", "matches_found"
        ):
            card["processing_stage"] = "ai_verified"

    # Propagate evidence_count for detail card display
    if proc.get("evidence_count"):
        card["evidence_count"] = proc["evidence_count"]
