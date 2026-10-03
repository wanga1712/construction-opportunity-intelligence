"""Factual Feeder V3 — Headless research pipeline feeder based on factual procurement state.

Admission authority is FACTUAL PROCUREMENT DATA (crm_procurements + canonical documents),
not old AI assessment.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras

from src.services.commercial_routing_v3.document_links import (
    batch_count_document_links,
    count_document_links,
    resolve_document_links,
)

logger = logging.getLogger("commercial_routing_v3.factual_feeder")

PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"
LOW_WATERMARK = 50
HIGH_WATERMARK = 200
FEED_BATCH_SIZE = 25
# Live lane = statuses that document workers are actually executing.
# The historical PRE_RESEARCH_WAITING holding backlog is NOT counted, so new
# live + actionable procurements are never blocked by old historical backlog.
LIVE_EXECUTABLE_STATUSES = ("PENDING", "RUNNING", "RETRY", "PROCESSING")


def _get_doc_db_conn():
    from dotenv import load_dotenv
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    load_dotenv("/opt/CRM_Streamlit/.env")
    crm_kwargs = require_crm_db_connect_kwargs()
    crm_kwargs["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    return psycopg2.connect(**crm_kwargs)


def compute_md5(data: Any) -> str:
    s = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class FactualFeeder:
    """Headless feeder that admits procurements into document_processing_queue based on factual procurement data."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def get_queue_depth(self) -> int:
        """Get count of active (PRE_RESEARCH_WAITING / PENDING / RUNNING / RETRY / PROCESSING) tasks in document_processing_queue."""
        conn = _get_doc_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM document_processing_queue WHERE pipeline_generation = %s AND status IN ('PRE_RESEARCH_WAITING', 'PENDING', 'RUNNING', 'RETRY', 'PROCESSING')",
                    (PIPELINE_GENERATION,),
                )
                res = cur.fetchone()
                return int(res[0]) if res else 0
        finally:
            conn.close()

    def load_factual_candidates(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch ACTIONABLE candidate procurements from crm_procurements (44-FZ and 223-FZ).

        Actionable means: open torgi submission window with at least MIN days left
        AND at least one canonical researchable document link. Expired, closed or
        link-less procurements are never admitted, so the live lane can never be
        starved or polluted by historical backlog.
        """
        sql = """
            SELECT DISTINCT ON (p.id) p.id, p.source_table, p.source_id, p.contract_number, p.okpd_code,
                   p.auction_name, p.end_date, p.crm_stage, p.award_status
            FROM crm_procurements p
            WHERE p.source_table IN ('reestr_contract_44_fz', 'reestr_contract_223_fz')
              AND p.crm_stage = 'torgi'
              AND p.award_status = 'submission_open'
              AND p.end_date >= CURRENT_DATE + INTERVAL '2 days'
            ORDER BY p.id DESC
            LIMIT %s
        """
        rows = [dict(r) for r in (self.crm_db.execute_query(sql, (limit,)) or [])]
        if not rows:
            return []

        # Cheap batched S7 lookup: keep only procurements that actually have
        # researchable canonical document links.
        try:
            counts = batch_count_document_links(rows, filter_unresearchable=True)
        except Exception as exc:
            logger.warning("candidate document link count failed: %s", exc)
            return []
        return [r for r in rows if int(counts.get(r["id"]) or 0) > 0]

    def admit_procurement(self, proc: Dict[str, Any], priors: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Check factual admission and enqueue into document_processing_queue if canonical documents exist."""
        procurement_id = proc["id"]
        source_table = proc.get("source_table") or ""
        source_id = proc.get("source_id")
        contract_number = proc.get("contract_number")
        okpd = proc.get("okpd_code")

        if priors is None:
            from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
            priors = load_okpd_priors_from_db(self.crm_db)

        from src.services.commercial_routing_v3.okpd_priors import (
            ADMISSION_OUT_OF_TARGET,
            ADMISSION_TARGET,
            ADMISSION_UNKNOWN_OKPD,
            classify_target_okpd,
        )

        classification, matched = classify_target_okpd(okpd, priors)

        # OUT_OF_TARGET: must not enter research queue
        if classification == ADMISSION_OUT_OF_TARGET:
            return {
                "procurement_id": procurement_id,
                "admitted": False,
                "reason": "OUT_OF_TARGET_OKPD",
                "classification": ADMISSION_OUT_OF_TARGET,
                "doc_count": 0,
            }

        # UNKNOWN_OKPD: must not enter executable research queue
        if classification == ADMISSION_UNKNOWN_OKPD:
            return {
                "procurement_id": procurement_id,
                "admitted": False,
                "reason": "UNKNOWN_OKPD",
                "classification": ADMISSION_UNKNOWN_OKPD,
                "doc_count": 0,
            }

        # ADMISSION-GATE (BUSINESS_RESEARCH_ADMISSION_V2): even OPEN candidates
        # require a current persisted ELIGIBLE scope decision. Missing / stale /
        # EXCLUDED / HOLD fails closed (no queue write).
        from src.services.commercial_routing_v3.business_research_admission import (
            context_admission_fields,
            is_queue_eligible,
            load_authority_map_exec,
        )

        admission = load_authority_map_exec(
            self.crm_db.execute_query, [procurement_id]
        ).get(procurement_id)
        if not is_queue_eligible(admission):
            return {
                "procurement_id": procurement_id,
                "admitted": False,
                "reason": "ADMISSION_"
                + str((admission or {}).get("admission_state") or "AUTHORITY_MISSING"),
                "classification": ADMISSION_TARGET,
                "doc_count": 0,
            }

        # Resolve canonical document links
        from src.services.commercial_routing_v3.card_research_state import compute_research_generation_hash
        doc_res = resolve_document_links(
            source_table=source_table,
            source_id=source_id,
            contract_number=contract_number,
        )
        links = doc_res.get("links") or []
        gen_hash = compute_research_generation_hash(procurement_id, links, PIPELINE_GENERATION)

        # Execute First Pass metadata assessment
        from src.services.first_pass.service import FirstPassService
        first_pass_svc = FirstPassService(self.crm_db)
        first_pass_res = first_pass_svc.evaluate_procurement(
            proc=proc,
            doc_count=len(links),
            priors=priors,
        )

        conn = _get_doc_db_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Check existing queue task for this procurement (any generation hash).
                cur.execute(
                    """
                    SELECT id, status, pipeline_generation, research_generation_hash
                    FROM document_processing_queue
                    WHERE procurement_id = %s AND pipeline_generation = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    (procurement_id, PIPELINE_GENERATION),
                )
                row = cur.fetchone()
                if row:
                    st = row.get("status")
                    row_hash = row.get("research_generation_hash") or ""
                    active_statuses = ("PRE_RESEARCH_WAITING", "PENDING", "RUNNING", "RETRY", "PROCESSING")
                    terminal_statuses = ("COMPLETED", "FAILED", "NO_LINKS")
                    if st in active_statuses or (st in terminal_statuses and row_hash == (gen_hash or "")):
                        reason = (
                            f"ALREADY_ACTIVE_IN_QUEUE_STATUS_{st}"
                            if st in active_statuses
                            else f"ALREADY_IN_QUEUE_STATUS_{st}"
                        )
                        return {
                            "procurement_id": procurement_id,
                            "admitted": False,
                            "reason": reason,
                            "classification": ADMISSION_TARGET,
                            "doc_count": len(links),
                            "queue_task_id": row["id"],
                            "first_pass_result": first_pass_res.to_dict(),
                        }

                # Determine status and context: TARGET procurement begins as PRE_RESEARCH_WAITING (or NO_LINKS)
                if not links:
                    status = "NO_LINKS"
                    category_context = {
                        "exclusion_reason": "NO_CANONICAL_DOCUMENTS",
                        **context_admission_fields(admission),
                    }
                else:
                    status = "PRE_RESEARCH_WAITING"
                    category_context = dict(context_admission_fields(admission))

                # Enqueue factual task with dynamic First Pass priority projection
                cur.execute(
                    """
                    INSERT INTO document_processing_queue (
                        procurement_id, source_table, source_id, contract_number,
                        research_action, queue_lane, priority_score, candidate_level,
                        candidate_score, procurement_scope_type, status,
                        pipeline_generation, research_generation_hash, category_context, created_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        'FACTUAL_FEEDER_ADMITTED', 'open_active', %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, NOW()
                    )
                    ON CONFLICT (procurement_id, pipeline_generation, research_generation_hash) DO NOTHING
                    RETURNING id
                    """,
                    (
                        procurement_id,
                        source_table,
                        source_id,
                        contract_number,
                        first_pass_res.priority_score,
                        first_pass_res.canonical_preliminary_medal,
                        first_pass_res.canonical_preliminary_score,
                        first_pass_res.object_family,
                        status,
                        PIPELINE_GENERATION,
                        gen_hash,
                        psycopg2.extras.Json(category_context),
                    ),
                )
                res = cur.fetchone()
                new_id = res["id"] if res else (row["id"] if row else None)
                conn.commit()

                return {
                    "procurement_id": procurement_id,
                    "admitted": status == "PRE_RESEARCH_WAITING",
                    "classification": ADMISSION_TARGET,
                    "queue_task_id": new_id,
                    "doc_count": len(links),
                    "status": status,
                    "first_pass_result": first_pass_res.to_dict(),
                }
        finally:
            conn.close()

    def get_live_lane_depth(self) -> int:
        """Count queue rows that document workers are actually executing."""
        conn = _get_doc_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM document_processing_queue WHERE pipeline_generation = %s AND status = ANY(%s)",
                    (PIPELINE_GENERATION, list(LIVE_EXECUTABLE_STATUSES)),
                )
                res = cur.fetchone()
                return int(res[0]) if res else 0
        finally:
            conn.close()

    def run_feeder_cycle(self) -> Dict[str, Any]:
        """Execute one bounded feeder cycle with live-lane watermark checks."""
        current_depth = self.get_queue_depth()
        live_depth = self.get_live_lane_depth()
        if live_depth >= HIGH_WATERMARK:
            return {
                "status": "HIGH_WATERMARK_REACHED",
                "queue_depth": current_depth,
                "live_lane_depth": live_depth,
                "admitted_count": 0,
            }

        from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
        priors = load_okpd_priors_from_db(self.crm_db)

        candidates = self.load_factual_candidates(limit=FEED_BATCH_SIZE * 40)
        admitted = 0
        results = []

        for cand in candidates:
            if live_depth + admitted >= HIGH_WATERMARK:
                break
            res = self.admit_procurement(cand, priors=priors)
            if res.get("admitted"):
                admitted += 1
            results.append(res)

        return {
            "status": "CYCLE_COMPLETED",
            "queue_depth_before": current_depth,
            "live_lane_depth_before": live_depth,
            "admitted_count": admitted,
            "queue_depth_after": self.get_queue_depth(),
            "live_lane_depth_after": self.get_live_lane_depth(),
            "results": results,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from src.services.db_bootstrap import connect_crm_database

    crm_db = connect_crm_database()
    feeder = FactualFeeder(crm_db)
    logger.info("Starting CRM V3 Factual Feeder loop (%s)", PIPELINE_GENERATION)
    while True:
        try:
            res = feeder.run_feeder_cycle()
            summary = {k: v for k, v in res.items() if k != "results"}
            admitted = int(res.get("admitted_count") or 0)
            logger.info("factual feeder cycle: %s", summary)
            time.sleep(30 if admitted else 60)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.exception("factual feeder cycle failed: %s", exc)
            time.sleep(30)
