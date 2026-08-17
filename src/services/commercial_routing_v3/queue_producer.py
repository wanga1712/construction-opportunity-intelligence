"""Queue producer V3 — opportunity-aware, procurement-scoped document jobs.

Writes ONLY to S13 document_intelligence. No S7 writes. Workers remain OFF.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from src.domain.commercial_routing_v3 import ResearchAction, ROUTING_VERSION
from src.services.commercial_routing_v3.document_priority import (
    CATEGORY_FAIR_SHARE_POLICY,
    DOCUMENT_PRIORITY_FORMULA,
    apply_category_fair_share,
    normalize_queue_lane,
)
from src.services.commercial_routing_v3.research_queue_lifecycle import (
    dry_run_research_admission,
    links_table_for_source,
)
from src.services.commercial_routing_v3.document_lane_authority import (
    apply_current_opportunity_authority,
)

logger = logging.getLogger("commercial_routing_v3.queue_producer")

_ACTION_MAP = {
    ResearchAction.LIGHT_RESEARCH.value: ("normal", "open_active", 30),
    ResearchAction.PRIORITY_DOCS.value: ("high", "crm_active_hot", 70),
    ResearchAction.DEEP_RESEARCH.value: ("highest", "crm_active_hot", 90),
    ResearchAction.DISCOVER_COMMERCIAL_CATEGORY.value: ("normal", "discovery_review", 40),
}
_SKIP = {ResearchAction.SKIP.value, ResearchAction.METADATA_ONLY.value}

PIPELINE_GENERATION = "S13_V2"
_DOC_ENV_FILES = (
    "/etc/tender-docs-db.env",
    "/opt/tender_documents_research/.env",
)


def _load_env_file(path: str) -> None:
    """Load document-DB credentials into S13_DOCUMENT_* only (never clobber DB_*)."""
    text = None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except PermissionError:
            text = None
    if text is None:
        try:
            import subprocess

            text = subprocess.check_output(["sudo", "cat", path], text=True)
        except Exception:
            return
    # tender-docs-db.env uses DB_* for document_intelligence — map only to S13_DOCUMENT_*.
    mapping = {
        "DB_HOST": "S13_DOCUMENT_DB_HOST",
        "DB_PORT": "S13_DOCUMENT_DB_PORT",
        "DB_DATABASE": "S13_DOCUMENT_DB_NAME",
        "DB_NAME": "S13_DOCUMENT_DB_NAME",
        "DB_USER": "S13_DOCUMENT_DB_USER",
        "DB_PASSWORD": "S13_DOCUMENT_DB_PASSWORD",
        "DOCUMENT_DB_HOST": "S13_DOCUMENT_DB_HOST",
        "DOCUMENT_DB_PORT": "S13_DOCUMENT_DB_PORT",
        "DOCUMENT_DB_NAME": "S13_DOCUMENT_DB_NAME",
        "DOCUMENT_DB_USER": "S13_DOCUMENT_DB_USER",
        "DOCUMENT_DB_PASSWORD": "S13_DOCUMENT_DB_PASSWORD",
        "S13_DOCUMENT_DB_HOST": "S13_DOCUMENT_DB_HOST",
        "S13_DOCUMENT_DB_PORT": "S13_DOCUMENT_DB_PORT",
        "S13_DOCUMENT_DB_NAME": "S13_DOCUMENT_DB_NAME",
        "S13_DOCUMENT_DB_USER": "S13_DOCUMENT_DB_USER",
        "S13_DOCUMENT_DB_PASSWORD": "S13_DOCUMENT_DB_PASSWORD",
    }
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key in mapping:
            os.environ.setdefault(mapping[key], val)


class CommercialRoutingV3QueueProducer:
    """Produces queue tasks from V3 category opportunities."""

    @staticmethod
    def _load_doc_env() -> None:
        for path in _DOC_ENV_FILES:
            _load_env_file(path)

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        # S13 local document_intelligence via CRM app role (never S7 tender-docs DB_*).
        self._doc_dsn = {
            "host": os.getenv("S13_DOCUMENT_DB_HOST")
            if os.getenv("S13_DOCUMENT_DB_HOST") not in (None, "", "S7")
            else "127.0.0.1",
            "port": int(
                os.getenv("S13_DOCUMENT_DB_PORT")
                or os.getenv("CRM_DB_PORT")
                or "5432"
            ),
            "dbname": "document_intelligence",
            "user": os.getenv("CRM_DB_USER") or "crm_app",
            "password": os.getenv("CRM_DB_PASSWORD") or "",
        }
        self._crm_dsn = {
            "host": os.getenv("CRM_DB_HOST"),
            "port": int(os.getenv("CRM_DB_PORT", "5432")),
            "dbname": os.getenv("CRM_DB_DATABASE"),
            "user": os.getenv("CRM_DB_USER"),
            "password": os.getenv("CRM_DB_PASSWORD"),
        }

    def decide_from_normalized(self, normalized: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        empty_st = str(normalized.get("empty_hypothesis_status") or "").upper()
        if empty_st == "NO_COMMERCIAL_ENTRY":
            return None
        hypotheses = (
            normalized.get("commercial_category_hypotheses")
            or normalized.get("category_opportunities")
            or []
        )
        discovery = bool(normalized.get("discovery_required"))
        overall = (normalized.get("overall_research_action") or "SKIP").upper()
        review_required = bool(normalized.get("review_required"))

        best_action = None
        best_depth = best_lane = None
        best_priority = 0
        trigger_opportunities: List[Dict[str, Any]] = []
        best_medal = "WOOD"
        best_track = None
        primary_category = None

        for h in hypotheses:
            action = (h.get("research_action") or "SKIP").upper()
            if action in _SKIP:
                continue
            trigger_opportunities.append(h)
            depth, lane, priority = _ACTION_MAP.get(action, ("normal", "open_active", 30))
            if priority > best_priority:
                best_priority = priority
                best_action = action
                best_depth = depth
                best_lane = lane
                best_medal = str(h.get("candidate_medal") or h.get("candidate_level") or "WOOD")
                best_track = h.get("opportunity_track")
                primary_category = h.get("category_code") or h.get("commercial_category_code")

        if best_action is None and (discovery or review_required) and overall not in _SKIP:
            best_action = (
                overall
                if overall in _ACTION_MAP
                else ResearchAction.DISCOVER_COMMERCIAL_CATEGORY.value
            )
            best_depth, best_lane, best_priority = _ACTION_MAP.get(
                best_action, ("normal", "discovery_review", 40)
            )

        if best_action is None:
            return None

        return {
            "research_action": best_action,
            "research_depth": best_depth,
            "queue_lane": best_lane,
            "priority_score": best_priority,
            "trigger_opportunities": trigger_opportunities,
            "discovery_required": discovery,
            "review_required": review_required,
            "analysis_modes": normalized.get("analysis_modes") or [],
            "routing_version": normalized.get("routing_version") or ROUTING_VERSION,
            "registry_version": normalized.get("registry_version"),
            "registry_hash": normalized.get("registry_hash"),
            "procurement_form": normalized.get("procurement_form"),
            "candidate_medal": best_medal,
            "opportunity_track": best_track,
            "primary_category": primary_category,
            "opportunity_associations": [
                {
                    "category_code": h.get("category_code") or h.get("commercial_category_code"),
                    "subcategory_code": h.get("subcategory_code"),
                    "opportunity_track": h.get("opportunity_track"),
                    "candidate_medal": h.get("candidate_medal") or h.get("candidate_level"),
                    "research_action": h.get("research_action"),
                }
                for h in trigger_opportunities
            ],
        }

    def upsert(
        self,
        procurement_id: int,
        decision: Dict[str, Any],
        *,
        dry_run: bool = True,
        procurement: Optional[Dict[str, Any]] = None,
        assessment_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if dry_run or not self.enabled:
            return {
                "action": "dry_run" if dry_run else "skipped_disabled",
                "procurement_id": procurement_id,
                **decision,
            }

        proc = procurement or self._load_procurement(procurement_id)
        if not proc:
            return {"action": "error", "procurement_id": procurement_id, "reason": "PROC_NOT_FOUND"}

        decision = apply_current_opportunity_authority(
            decision, self._load_current_opportunities(procurement_id)
        )

        # Lifecycle admission (HOLD / CLOSED / ELIGIBLE)
        hyps = decision.get("trigger_opportunities") or []
        track = decision.get("opportunity_track") or (hyps[0].get("opportunity_track") if hyps else None)
        medal = decision.get("candidate_medal") or (hyps[0].get("candidate_medal") if hyps else None)
        admission = dry_run_research_admission(
            procurement=proc,
            opportunity_track=track,
            discovery_required=bool(decision.get("discovery_required")),
            review_required=bool(decision.get("review_required")),
            has_valid_category=bool(hyps),
            routed=True,
            research_action=decision.get("research_action"),
            current_effective_medal=medal,
            commercial_state=decision.get("commercial_state"),
        )
        lane_norm = normalize_queue_lane(admission.research_lane, admission.queue_state)
        end = proc.get("end_date")
        urg = 9999
        if end is not None:
            try:
                d = end if hasattr(end, "year") else date.fromisoformat(str(end)[:10])
                urg = max(0, (d - date.today()).days)
            except Exception:
                urg = 9999

        link_count = self._count_links(proc)
        track_u = str(track or "").upper()
        action_u = str(decision.get("research_action") or "").upper()
        assess_status = str(
            (procurement or {}).get("assessment_status")
            or (procurement or {}).get("ai_assessment_status")
            or ""
        ).upper()

        # Hard non-executable contracts
        empty_st = str(
            decision.get("empty_hypothesis_status")
            or (procurement or {}).get("empty_hypothesis_status")
            or ""
        ).upper()
        if empty_st == "NO_COMMERCIAL_ENTRY" or track_u == "NO_COMMERCIAL_ENTRY":
            return {
                "action": "analytics_only",
                "status": "NO_COMMERCIAL_ENTRY_NOT_EXECUTABLE",
                "dispatchable": False,
                "link_count": link_count,
                "reason": "empty_hypothesis_status=NO_COMMERCIAL_ENTRY"
                if empty_st == "NO_COMMERCIAL_ENTRY"
                else "opportunity_track=NO_COMMERCIAL_ENTRY",
                "procurement_id": procurement_id,
                "research_action": ResearchAction.SKIP.value,
                "opportunity_track": track or "NO_COMMERCIAL_ENTRY",
            }
        if action_u in _SKIP or action_u in ("SKIP", "METADATA_ONLY"):
            return {
                "action": "analytics_only",
                "status": "SKIP_NOT_EXECUTABLE",
                "dispatchable": False,
                "link_count": link_count,
                "reason": "research_action=SKIP",
                **{k: decision.get(k) for k in ("research_action", "opportunity_track", "candidate_medal", "primary_category")},
                "procurement_id": procurement_id,
            }
        if assess_status == "FAILED" or action_u == "FAILED":
            return {
                "action": "analytics_only",
                "status": "FAILED_NOT_EXECUTABLE",
                "dispatchable": False,
                "link_count": link_count,
                "reason": "assessment_or_action=FAILED",
                "procurement_id": procurement_id,
            }
        if str(decision.get("candidate_medal") or "").upper() == "WOOD":
            return {
                "action": "analytics_only",
                "status": "WOOD_NOT_AUTO_EXECUTABLE",
                "dispatchable": False,
                "link_count": link_count,
                "reason": "WOOD_NOT_AUTO_EXECUTABLE",
                "procurement_id": procurement_id,
            }

        task = {
            "procurement_id": procurement_id,
            "source_table": proc.get("source_table") or "",
            "source_id": proc.get("source_id"),
            "contract_number": proc.get("contract_number"),
            "assessment_id": assessment_id,
            "category_codes": [
                a.get("category_code")
                for a in (decision.get("opportunity_associations") or [])
                if a.get("category_code")
            ],
            "category_context": {
                "opportunity_associations": decision.get("opportunity_associations") or [],
                "admission": admission.to_dict(),
                "queue_lane_normalized": lane_norm,
                "link_count": link_count,
                "document_priority_formula": DOCUMENT_PRIORITY_FORMULA,
                "category_fair_share_policy": CATEGORY_FAIR_SHARE_POLICY,
            },
            "candidate_level": decision.get("candidate_medal"),
            "candidate_score": None,
            "research_action": decision.get("research_action"),
            "research_depth": decision.get("research_depth"),
            "queue_lane": admission.research_lane or decision.get("queue_lane"),
            "priority_score": admission.research_priority or decision.get("priority_score") or 0,
            "queue_state": admission.queue_state,
            "research_lane": admission.research_lane,
            "opportunity_track": track,
            "candidate_medal": decision.get("candidate_medal"),
            "primary_category": decision.get("primary_category"),
            "deadline_urgency_days": urg,
            "link_count": link_count,
            "dispatchable": bool(admission.queue_eligible) and link_count > 0,
        }

        # Status CHECK allows only PENDING/PROCESSING/COMPLETED/FAILED/NO_LINKS.
        # HOLD/CLOSED are not executable queue rows — return analytics-only decision.
        if not admission.queue_eligible:
            return {
                "action": "analytics_only",
                "status": admission.queue_state,
                "dispatchable": False,
                **task,
            }
        if link_count == 0:
            # Desired research but unresolved links — NOT executable PENDING
            return {
                "action": "analytics_only",
                "status": "NO_LINKS",
                "dispatchable": False,
                "reason": "ZERO_LINK_NOT_EXECUTABLE",
                **task,
            }
        status = "PENDING"
        return self._upsert_queue_task(task, status=status)

    def produce_for_procurements(
        self,
        procurement_ids: List[int],
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        produced = skipped = updated = errors = held = closed = 0
        tasks: List[Dict[str, Any]] = []
        for pid in procurement_ids:
            try:
                row = self._load_assessment(pid)
                if not row:
                    skipped += 1
                    continue
                normalized = row.get("normalized_result") or {}
                if isinstance(normalized, str):
                    normalized = json.loads(normalized)
                decision = self.decide_from_normalized(normalized)
                if not decision:
                    skipped += 1
                    continue
                result = self.upsert(
                    pid,
                    decision,
                    dry_run=dry_run,
                    procurement=row,
                    assessment_id=row.get("assessment_id"),
                )
                action = result.get("action")
                if action == "inserted":
                    produced += 1
                    tasks.append(result)
                elif action == "updated":
                    updated += 1
                    tasks.append(result)
                elif result.get("queue_state") == "HOLD" or result.get("status") == "HOLD":
                    held += 1
                    tasks.append(result)
                elif result.get("status") == "CLOSED":
                    closed += 1
                    tasks.append(result)
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                logger.exception("queue produce failed pid=%s: %s", pid, exc)

        ranked = apply_category_fair_share(
            [t for t in tasks if t.get("procurement_id")]
        )
        # rewrite priorities for dispatchable only
        self._apply_ranked_priorities(ranked, dry_run=dry_run)

        return {
            "pipeline": PIPELINE_GENERATION,
            "V3_RESEARCH_QUEUE_PRODUCER_ENABLED": "YES" if self.enabled else "NO",
            "produced": produced,
            "updated": updated,
            "skipped": skipped,
            "held": held,
            "closed": closed,
            "errors": errors,
            "tasks": ranked,
            "DUPLICATE_DOWNLOAD_JOB_PER_PROCUREMENT": self._duplicate_job_count(procurement_ids),
            "DOCUMENT_PRIORITY_FORMULA": DOCUMENT_PRIORITY_FORMULA,
            "CATEGORY_FAIR_SHARE_POLICY": CATEGORY_FAIR_SHARE_POLICY,
        }

    def _apply_ranked_priorities(self, ranked: List[Dict[str, Any]], *, dry_run: bool) -> None:
        if dry_run:
            return
        doc = psycopg2.connect(**self._doc_dsn)
        try:
            with doc.cursor() as cur:
                for row in ranked:
                    if not row.get("dispatchable"):
                        continue
                    cur.execute(
                        """
                        UPDATE document_processing_queue
                           SET priority_score = %s
                         WHERE procurement_id = %s
                           AND pipeline_generation = %s
                        """,
                        (
                            int(row.get("document_priority") or row.get("priority_score") or 0),
                            int(row["procurement_id"]),
                            PIPELINE_GENERATION,
                        ),
                    )
            doc.commit()
        finally:
            doc.close()

    def _duplicate_job_count(self, procurement_ids: List[int]) -> int:
        if not procurement_ids:
            return 0
        doc = psycopg2.connect(**self._doc_dsn)
        try:
            with doc.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM (
                      SELECT procurement_id
                      FROM document_processing_queue
                      WHERE pipeline_generation = %s
                        AND procurement_id = ANY(%s)
                      GROUP BY procurement_id
                      HAVING COUNT(*) > 1
                    ) d
                    """,
                    (PIPELINE_GENERATION, procurement_ids),
                )
                return int(cur.fetchone()[0])
        finally:
            doc.close()

    def _load_procurement(self, procurement_id: int) -> Optional[Dict[str, Any]]:
        crm = psycopg2.connect(**self._crm_dsn)
        try:
            with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, source_table, source_id, contract_number, end_date,
                           auction_name, okpd_code, crm_stage, award_status
                    FROM crm_procurements WHERE id = %s
                    """,
                    (procurement_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            crm.close()

    def _load_assessment(self, procurement_id: int) -> Optional[Dict[str, Any]]:
        crm = psycopg2.connect(**self._crm_dsn)
        try:
            with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT a.id AS assessment_id, a.procurement_id, a.normalized_result,
                           a.status AS assessment_status,
                           p.source_table, p.source_id, p.contract_number, p.end_date,
                           p.auction_name, p.okpd_code, p.crm_stage, p.award_status,
                           p.ai_assessment_status
                    FROM procurement_ai_assessments a
                    JOIN crm_procurements p ON p.id = a.procurement_id
                    WHERE a.procurement_id = %s
                      AND a.is_current = TRUE
                      AND a.is_stale = FALSE
                    ORDER BY a.id DESC
                    LIMIT 1
                    """,
                    (procurement_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            crm.close()

    def _load_current_opportunities(self, procurement_id: int) -> List[Dict[str, Any]]:
        if not self._crm_dsn.get("host"):
            return []
        try:
            crm = psycopg2.connect(**self._crm_dsn)
        except Exception:
            return []
        try:
            with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT commercial_category_code, commercial_subcategory_code AS subcategory_code,
                           opportunity_track,
                           research_action, current_effective_medal, candidate_medal,
                           commercial_state, commercial_priority_score
                    FROM crm_procurement_category_opportunities
                    WHERE procurement_id = %s AND status = 'CURRENT'
                    """,
                    (procurement_id,),
                )
                return [dict(r) for r in (cur.fetchall() or [])]
        except Exception:
            logger.warning("current opportunity load failed pid=%s", procurement_id)
            return []
        finally:
            crm.close()

    def _count_links(self, proc: Dict[str, Any]) -> int:
        from src.services.commercial_routing_v3.document_links import count_document_links

        return count_document_links(
            source_table=str(proc.get("source_table") or ""),
            source_id=proc.get("source_id"),
            contract_number=proc.get("contract_number"),
        )

    def _upsert_queue_task(self, task: Dict[str, Any], *, status: str = "PENDING") -> Dict[str, Any]:
        sql_check = """
            SELECT id, research_depth FROM document_processing_queue
            WHERE procurement_id = %s AND pipeline_generation = %s
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
                (%s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s, %s,%s, %s,%s)
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
                   status           = %s,
                   last_error       = NULL,
                   worker_id        = NULL,
                   started_at       = NULL,
                   completed_at     = NULL
             WHERE id = %s
        """
        doc = psycopg2.connect(**self._doc_dsn)
        doc.autocommit = False
        try:
            with doc.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql_check, (task["procurement_id"], PIPELINE_GENERATION))
                existing = cur.fetchone()
                if existing is None:
                    cur.execute(
                        sql_insert,
                        (
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
                            status,
                            PIPELINE_GENERATION,
                        ),
                    )
                    row = cur.fetchone()
                    doc.commit()
                    return {"action": "inserted", "queue_id": row["id"], "status": status, **task}
                cur.execute(
                    sql_update,
                    (
                        task["research_action"],
                        task["research_depth"],
                        task["queue_lane"],
                        task["priority_score"],
                        task["assessment_id"],
                        task["category_codes"],
                        psycopg2.extras.Json(task["category_context"]),
                        task["candidate_level"],
                        task["candidate_score"],
                        status,
                        existing["id"],
                    ),
                )
                doc.commit()
                return {"action": "updated", "queue_id": existing["id"], "status": status, **task}
        except Exception:
            doc.rollback()
            raise
        finally:
            doc.close()
