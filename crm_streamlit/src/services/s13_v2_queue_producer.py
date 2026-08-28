"""
S13V2QueueProducer: AI assessment → document_intelligence queue bridge.

Reads CURRENT non-stale procurement_ai_assessments,
maps research_action per category_opportunity → queue task.

All DB hosts read from env (no hardcoded IPs).
CRM DB = env CRM_DB_* (currently S7, will move to S13 in CRM-DB-S13-CUTOVER-1).
Doc DB = env S13_DOCUMENT_DB_* (S13 local).

research_action → queue mapping:
  SKIP, METADATA_ONLY        → no task
  LIGHT_RESEARCH             → depth=normal,  lane=open_active,    priority=30
  PRIORITY_DOCS              → depth=high,    lane=crm_active_hot, priority=70
  DEEP_RESEARCH              → depth=highest, lane=crm_active_hot, priority=90
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

PIPELINE_GENERATION = "S13_V2"

# research_action → (depth, lane, priority_score)
_ACTION_MAP: Dict[str, tuple[str, str, int]] = {
    "LIGHT_RESEARCH": ("normal",   "open_active",    30),
    "PRIORITY_DOCS":  ("high",     "crm_active_hot", 70),
    "DEEP_RESEARCH":  ("highest",  "crm_active_hot", 90),
}
_SKIP_ACTIONS = {"SKIP", "METADATA_ONLY"}
_ACTION_RANK = {"normal": 1, "high": 2, "highest": 3}


def _depth_rank(depth: Optional[str]) -> int:
    return _ACTION_RANK.get(depth or "", 0)


class S13V2QueueProducer:
    """
    Produces S13_V2 queue tasks from current AI assessments.

    Usage:
        producer = S13V2QueueProducer()
        report = producer.run(procurement_id=1234)        # single
        report = producer.run()                           # all non-stale pending
    """

    def __init__(self) -> None:
        self._crm_dsn = {
            "host":     os.getenv("CRM_DB_HOST"),
            "port":     int(os.getenv("CRM_DB_PORT", "5432")),
            "dbname":   os.getenv("CRM_DB_DATABASE"),
            "user":     os.getenv("CRM_DB_USER"),
            "password": os.getenv("CRM_DB_PASSWORD"),
        }
        self._doc_dsn = {
            "host":     os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
            "port":     int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
            "dbname":   os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
            "user":     os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
            "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
        }

    # ── public API ────────────────────────────────────────────────────────────

    def run(
        self,
        procurement_id: Optional[int] = None,
        dry_run: bool = False,
        limit: int = 500,
    ) -> Dict[str, Any]:
        """
        Produce queue tasks.
        Returns report: {produced, skipped, updated, errors, tasks: [...]}.
        """
        assessments = self._fetch_assessments(procurement_id, limit)
        logger.info(f"[S13V2QueueProducer] Assessments fetched: {len(assessments)}")

        produced = skipped = updated = errors = 0
        tasks_out: List[Dict[str, Any]] = []

        for a in assessments:
            try:
                result = self._process_assessment(a, dry_run=dry_run)
                if result is None:
                    skipped += 1
                elif result.get("action") == "inserted":
                    produced += 1
                    tasks_out.append(result)
                elif result.get("action") == "updated":
                    updated += 1
                    tasks_out.append(result)
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                logger.error(
                    f"[S13V2QueueProducer] Error for procurement {a.get('procurement_id')}: {exc}",
                    exc_info=True,
                )

        report = {
            "pipeline": PIPELINE_GENERATION,
            "assessments_read": len(assessments),
            "produced": produced,
            "skipped": skipped,
            "updated": updated,
            "errors": errors,
            "tasks": tasks_out,
        }
        logger.info(f"[S13V2QueueProducer] Done: {report}")
        return report

    # ── internals ─────────────────────────────────────────────────────────────

    def _fetch_assessments(
        self, procurement_id: Optional[int], limit: int
    ) -> List[Dict[str, Any]]:
        """
        Fetch current non-stale assessments that have research opportunities.
        Reads crm.procurement_ai_assessments + crm.crm_procurements.
        """
        sql = """
            SELECT
                a.id            AS assessment_id,
                a.procurement_id,
                a.normalized_result,
                a.proposed_level   AS candidate_level,
                a.confidence       AS candidate_score,
                a.is_stale,
                p.source_table,
                p.source_id,
                p.contract_number
            FROM procurement_ai_assessments a
            JOIN crm_procurements p ON p.id = a.procurement_id
            WHERE a.is_current = TRUE
              AND a.is_stale   = FALSE
              AND a.status     = 'SUCCESS'
              AND a.normalized_result IS NOT NULL
        """
        params: list = []
        if procurement_id is not None:
            sql += " AND a.procurement_id = %s"
            params.append(procurement_id)
        else:
            sql += " LIMIT %s"
            params.append(limit)

        crm = psycopg2.connect(**self._crm_dsn)
        crm.autocommit = True
        try:
            with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            crm.close()

        if not rows and procurement_id is not None and os.getenv("LEARNING_MODE") == "EXHAUSTIVE_EVIDENCE_BASELINE":
            sql_fallback = """
                SELECT 
                    NULL AS assessment_id,
                    id AS procurement_id,
                    '{}'::jsonb AS normalized_result,
                    'SILVER' AS candidate_level,
                    1.0 AS candidate_score,
                    FALSE AS is_stale,
                    source_table,
                    source_id,
                    contract_number
                FROM crm_procurements
                WHERE id = %s
            """
            crm = psycopg2.connect(**self._crm_dsn)
            crm.autocommit = True
            try:
                with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql_fallback, (procurement_id,))
                    rows = cur.fetchall()
            finally:
                crm.close()

        return [dict(r) for r in rows]

    def _process_assessment(
        self, a: Dict[str, Any], dry_run: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Parse normalized_result, determine aggregate research action,
        upsert into document_intelligence.document_processing_queue.
        Returns dict with action='inserted'|'updated'|'skipped', or None.
        """
        if os.getenv("LEARNING_MODE") == "EXHAUSTIVE_EVIDENCE_BASELINE":
            # Load all active categories to prevent skips and establish a complete baseline
            crm = psycopg2.connect(**self._crm_dsn)
            try:
                with crm.cursor() as cur:
                    cur.execute("SELECT category_code FROM crm_product_categories WHERE is_active = TRUE")
                    active_categories = [r[0] for r in cur.fetchall() if r[0]]
            finally:
                crm.close()

            category_context = {
                cat: {
                    "research_action": "DEEP_RESEARCH",
                    "priority": 100,
                    "expected_role": "DIRECT_SUPPLY",
                    "commercial_entry_point": "YES"
                }
                for cat in active_categories
            }

            task = {
                "procurement_id":  a["procurement_id"],
                "source_table":    a.get("source_table", ""),
                "source_id":       a.get("source_id"),
                "contract_number": a.get("contract_number"),
                "assessment_id":   a["assessment_id"],
                "category_codes":  active_categories,
                "category_context": category_context,
                "candidate_level": a.get("candidate_level"),
                "candidate_score": float(a["candidate_score"]) if a.get("candidate_score") else None,
                "research_action": "DEEP_RESEARCH",
                "research_depth":  "highest",
                "queue_lane":      "learning_baseline",
                "priority_score":  100,
            }
            if dry_run:
                return {"action": "dry_run", **task}
            return self._upsert_queue_task(task)

        normalized = a.get("normalized_result") or {}
        if isinstance(normalized, str):
            try:
                normalized = json.loads(normalized)
            except Exception:
                return None

        opportunities = normalized.get("category_opportunities") or []
        discovery_required = bool(normalized.get("discovery_required"))
        overall_research_action = (
            (normalized.get("overall_research_action") or "").strip().upper()
        )

        # Aggregate: find maximum research_action across all opportunities
        best_depth: Optional[str] = None
        best_action: Optional[str] = None
        best_lane: Optional[str] = None
        best_priority: int = 0
        active_categories: List[str] = []
        category_context: Dict[str, Any] = {}

        for opp in opportunities:
            action = (opp.get("research_action") or "").strip().upper()
            if action in _SKIP_ACTIONS or action not in _ACTION_MAP:
                continue

            depth, lane, priority = _ACTION_MAP[action]
            cat_code = opp.get("category_code", "")
            if cat_code:
                active_categories.append(cat_code)
                category_context[cat_code] = {
                    "research_action": action,
                    "priority": opp.get("priority"),
                    "expected_role": opp.get("expected_role"),
                    "commercial_entry_point": opp.get("commercial_entry_point"),
                }

            if _depth_rank(depth) > _depth_rank(best_depth):
                best_depth = depth
                best_action = action
                best_lane = lane
                best_priority = priority

        if best_action is None:
            # All opportunities are SKIP/METADATA_ONLY.
            # V3 contract: allow discovery routing even when category list is empty.
            if (
                discovery_required
                and overall_research_action
                and overall_research_action in _ACTION_MAP
            ):
                best_action = overall_research_action
                best_depth, best_lane, best_priority = _ACTION_MAP[overall_research_action]
            else:
                return None

        if not active_categories and not (
            discovery_required and best_action in _ACTION_MAP
        ):
            return None

        task = {
            "procurement_id":  a["procurement_id"],
            "source_table":    a.get("source_table", ""),
            "source_id":       a.get("source_id"),
            "contract_number": a.get("contract_number"),
            "assessment_id":   a["assessment_id"],
            "category_codes":  active_categories,
            "category_context": category_context,
            "candidate_level": a.get("candidate_level"),
            "candidate_score": float(a["candidate_score"]) if a.get("candidate_score") else None,
            "research_action": best_action,
            "research_depth":  best_depth,
            "queue_lane":      best_lane,
            "priority_score":  best_priority,
        }

        if dry_run:
            return {"action": "dry_run", **task}

        return self._upsert_queue_task(task)

    def _get_doc_conn(self) -> psycopg2.extensions.connection:
        """Self-healing connection to document intelligence DB on localhost S13."""
        host = self._doc_dsn.get("host", "127.0.0.1")
        port = self._doc_dsn.get("port", 5432)
        dbname = self._doc_dsn.get("dbname", "document_intelligence")
        user = self._doc_dsn.get("user", "doc_worker")
        
        pwd = self._doc_dsn.get("password", "")
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=pwd,
            connect_timeout=3
        )
        return conn

    def _upsert_queue_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert or update queue task in document_intelligence DB.
        Upgrade research_depth if new > existing.
        Returns dict with action='inserted'|'updated'|'skipped'.
        """
        sql_check = """
            SELECT id, research_depth FROM document_processing_queue
            WHERE procurement_id = %s AND pipeline_generation = 'S13_V2'
        """
        sql_insert = """
            INSERT INTO document_processing_queue
                (procurement_id, source_table, source_id, contract_number,
                 assessment_id, category_codes, category_context,
                 candidate_level, candidate_score,
                 research_action, research_depth,
                 queue_lane, priority_score,
                 status, pipeline_generation)
            VALUES
                (%s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s, %s,%s, 'PENDING','S13_V2')
            RETURNING id
        """
        sql_update = """
            UPDATE document_processing_queue
               SET research_action  = %s,
                   research_depth   = %s,
                   queue_lane       = %s,
                   priority_score   = %s,
                   assessment_id    = %s,
                   category_codes   = %s,
                   category_context = %s,
                   candidate_level  = %s,
                   candidate_score  = %s,
                   status           = 'PENDING'
             WHERE id = %s
        """

        doc = self._get_doc_conn()
        doc.autocommit = False
        try:
            with doc.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_check, (task["procurement_id"],))
                existing = cur.fetchone()

                if existing is None:
                    cur.execute(sql_insert, (
                        task["procurement_id"],
                        task["source_table"],
                        task["source_id"],
                        task["contract_number"],
                        task["assessment_id"],
                        task["category_codes"],
                        psycopg2.extras.Json(task["category_context"]),
                        task["candidate_level"],
                        task["candidate_score"],
                        task["research_action"],
                        task["research_depth"],
                        task["queue_lane"],
                        task["priority_score"],
                    ))
                    row = cur.fetchone()
                    doc.commit()
                    return {"action": "inserted", "queue_id": row["id"], **task}

                ex_rank = _depth_rank(existing["research_depth"])
                new_rank = _depth_rank(task["research_depth"])
                if new_rank > ex_rank:
                    cur.execute(sql_update, (
                        task["research_action"],
                        task["research_depth"],
                        task["queue_lane"],
                        task["priority_score"],
                        task["assessment_id"],
                        task["category_codes"],
                        psycopg2.extras.Json(task["category_context"]),
                        task["candidate_level"],
                        task["candidate_score"],
                        existing["id"],
                    ))
                    doc.commit()
                    return {"action": "updated", "queue_id": existing["id"], **task}

                return {"action": "skipped", "queue_id": existing["id"],
                        "reason": "existing_depth_ge_new"}

        except Exception:
            doc.rollback()
            raise
        finally:
            doc.close()
