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
from tender_documents_research.document_processor.research_dedup import (
    canonical_research_identity,
    canonical_identity_sql,
    research_disposition,
)

logger = logging.getLogger("commercial_routing_v3.queue_producer")

_ACTION_MAP = {
    ResearchAction.LIGHT_RESEARCH.value: ("normal", "open_active", 30),
    ResearchAction.PRIORITY_DOCS.value: ("high", "crm_active_hot", 70),
    ResearchAction.DEEP_RESEARCH.value: ("highest", "crm_active_hot", 90),
    ResearchAction.DISCOVER_COMMERCIAL_CATEGORY.value: ("normal", "discovery_review", 40),
}
_SKIP = {ResearchAction.SKIP.value, ResearchAction.METADATA_ONLY.value}

PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"
_DOC_ENV_FILES = (
    "/etc/tender-docs-db.env",
    "/opt/tender_documents_research/.env",
)


def _document_dsn_from_env() -> dict[str, Any]:
    """Build the document DB DSN only from the document credential authority."""
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST")
        if os.getenv("S13_DOCUMENT_DB_HOST") not in (None, "", "S7")
        else "127.0.0.1",
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT") or "5432"),
        "dbname": "document_intelligence",
        "user": os.getenv("S13_DOCUMENT_DB_USER") or "",
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD") or "",
    }


def _load_doc_env() -> None:
    for f in _DOC_ENV_FILES:
        if os.path.exists(f):
            _load_env_file(f)

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
        self._doc_dsn = _document_dsn_from_env()
        self._crm_dsn = {
            "host": os.getenv("CRM_DB_HOST"),
            "port": int(os.getenv("CRM_DB_PORT", "5432")),
            "dbname": os.getenv("CRM_DB_DATABASE"),
            "user": os.getenv("CRM_DB_USER"),
            "password": os.getenv("CRM_DB_PASSWORD"),
        }

    def decide_from_normalized(self, normalized: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # AI_QUEUE_ADMISSION_GATE=NO: NO_COMMERCIAL_ENTRY does NOT gate queue admission.
        # All lifecycle-eligible procurements use populate_all_eligible() directly.
        # decide_from_normalized retained for legacy assessment-driven flow compatibility.
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

    # ------------------------------------------------------------------
    # STEP 3/4: V4 population from the persisted business authority.
    # Stage1 priority is applied only after admission_state=ELIGIBLE.
    # ------------------------------------------------------------------

    _TERMINAL_STAGES = frozenset([
        "cancelled", "failed", "closed", "rejected",
        "archived", "no_winner", "suspended",
    ])

    def populate_all_eligible(
        self,
        *,
        batch_size: int = 500,
        max_total: int = 0,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Queue current, authority-admitted procurements from CRM.

        Eligibility criteria (deterministic, no AI):
          - current CRM open/awarded lifecycle
          - scope authority with admission_state=ELIGIBLE
          - Not already queued for this pipeline_generation

        The model controls ordering only; it does not control admission.
        """
        from src.services.commercial_routing_v3.document_links import batch_count_document_links
        from src.services.commercial_routing_v3.okpd_priors import (
            ADMISSION_OUT_OF_TARGET,
            ADMISSION_TARGET,
            ADMISSION_UNKNOWN_OKPD,
            classify_target_okpd,
            load_okpd_priors_from_db,
        )

        inserted = updated = skipped_already_active = errors = 0
        skipped_out_of_target = skipped_unknown_okpd = 0
        target_waiting_inserted = target_waiting_updated = 0
        no_links_inserted = no_links_updated = 0
        offset = 0

        crm = psycopg2.connect(**self._crm_dsn)
        crm.autocommit = True
        try:
            class CrmDbWrapper:
                def __init__(self, conn):
                    self.conn = conn
                def execute_query(self, sql, params=None):
                    with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(sql, params)
                        return cur.fetchall()

            crm_wrapper = CrmDbWrapper(crm)
            priors = load_okpd_priors_from_db(crm_wrapper)
            logger.info("Loaded %d active OKPD priors from CRM database", len(priors))

            while True:
                with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT p.id, p.source_table, p.source_id, p.contract_number,
                               p.end_date, p.crm_stage, p.award_status, p.okpd_code,
                               a.procurement_scope_type, a.scope_confidence,
                               a.admission_state, a.admission_reason,
                               a.admission_policy_version, a.admission_evaluated_at,
                               a.scope_version, a.source_lifecycle
                        FROM crm_procurements p
                        JOIN crm_procurement_scope_authority a
                          ON a.procurement_id = p.id
                         AND a.admission_state = 'ELIGIBLE'
                        WHERE (
                            (p.crm_stage = 'torgi' AND p.award_status = 'submission_open')
                            OR p.crm_stage = 'razygranye'
                        )
                        ORDER BY p.id
                        LIMIT %s OFFSET %s
                        """,
                        (batch_size, offset),
                    )
                    rows = cur.fetchall()

                if not rows:
                    break
                offset += len(rows)

                # Batch count document links to avoid N+1 queries
                link_counts = batch_count_document_links(rows)

                # Open a single connection to Document DB for this batch
                doc_conn = psycopg2.connect(**self._doc_dsn)
                doc_conn.autocommit = False
                try:
                    for proc in rows:
                        pid = proc["id"]
                        if max_total and (inserted + updated) >= max_total:
                            break
                        try:
                            okpd = proc.get("okpd_code")
                            classification, matched_priors = classify_target_okpd(okpd, priors)

                            if classification == ADMISSION_OUT_OF_TARGET:
                                skipped_out_of_target += 1
                                continue

                            if classification == ADMISSION_UNKNOWN_OKPD:
                                skipped_unknown_okpd += 1
                                continue

                            # TARGET procurement
                            lc = link_counts.get(pid, 0)

                            if lc == 0:
                                status = "NO_LINKS"
                                category_context = {
                                    "populate_method": "EXHAUSTIVE_ALL_ELIGIBLE",
                                    "admission_state": proc["admission_state"],
                                    "admission_reason": proc["admission_reason"],
                                    "admission_policy_version": proc["admission_policy_version"],
                                    "admission_evaluated_at": (
                                        proc["admission_evaluated_at"].isoformat()
                                        if proc["admission_evaluated_at"] is not None else None
                                    ),
                                    "authority_scope_version": proc["scope_version"],
                                    "procurement_scope_type": proc["procurement_scope_type"],
                                    "link_count": 0,
                                    "exclusion_reason": "NO_CANONICAL_DOCUMENTS",
                                }
                                dispatchable = False
                            else:
                                status = "PRE_RESEARCH_WAITING"
                                category_context = {
                                    "populate_method": "EXHAUSTIVE_ALL_ELIGIBLE",
                                    "admission_state": proc["admission_state"],
                                    "admission_reason": proc["admission_reason"],
                                    "admission_policy_version": proc["admission_policy_version"],
                                    "admission_evaluated_at": (
                                        proc["admission_evaluated_at"].isoformat()
                                        if proc["admission_evaluated_at"] is not None else None
                                    ),
                                    "authority_scope_version": proc["scope_version"],
                                    "procurement_scope_type": proc["procurement_scope_type"],
                                    "link_count": lc,
                                }
                                dispatchable = True

                            task = {
                                "procurement_id": pid,
                                "source_table": proc.get("source_table") or "",
                                "source_id": proc.get("source_id"),
                                "contract_number": proc.get("contract_number"),
                                "assessment_id": None,
                                "category_codes": [
                                    p.get("commercial_category_code")
                                    for p in matched_priors
                                    if p.get("commercial_category_code")
                                ],
                                "category_context": category_context,
                                "candidate_level": None,
                                "candidate_score": None,
                                "research_action": ResearchAction.DEEP_RESEARCH.value,
                                "research_depth": "highest",
                                "queue_lane": (
                                    "awarded_recent"
                                    if proc["source_lifecycle"] == "AWARDED"
                                    else "open_active"
                                ),
                                "priority_score": 50,
                                "dispatchable": dispatchable,
                            }
                            identity = canonical_research_identity(
                                source_family=task["source_table"],
                                notice_number=task["contract_number"],
                                procurement_id=task["procurement_id"],
                            )
                            task["research_identity_key"] = identity.key
                            category_context["research_identity_key"] = identity.key

                            if dry_run:
                                with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as check_cur:
                                    check_cur.execute(
                                        f"""
                                        SELECT CASE
                                                   WHEN q.status = 'COMPLETED'
                                                    AND NOT EXISTS (
                                                        SELECT 1
                                                          FROM document_processing_results r2
                                                         WHERE r2.queue_id = q.id
                                                           AND r2.status = 'COMPLETED'
                                                    ) THEN 'PARTIAL'
                                                   ELSE q.status
                                               END AS status,
                                               EXISTS (
                                                   SELECT 1
                                                     FROM document_processing_results r
                                                    WHERE r.queue_id = q.id
                                                      AND r.status = 'COMPLETED'
                                               ) AS successful_parse
                                         FROM document_processing_queue q
                                         WHERE {canonical_identity_sql("q")} = %s
                                            OR (q.contract_number IS NULL AND q.procurement_id = %s)
                                         ORDER BY successful_parse DESC, q.id
                                        """,
                                        (identity.key, task["procurement_id"]),
                                    )
                                    existing = check_cur.fetchall()
                                    disposition = research_disposition(
                                        existing,
                                        canonical_links_available=bool(task["category_context"].get("link_count")),
                                    )
                                    if disposition == "NEW_RESEARCH_ALLOWED":
                                        action = "inserted"
                                    elif disposition == "RETRY_EXISTING_IDENTITY":
                                        action = "updated"
                                    elif disposition == "REUSE_EXISTING_RESEARCH":
                                        action = "reused_existing_research"
                                    else:
                                        action = "skipped_already_active"
                            else:
                                result = self._upsert_queue_task(task, status=status, conn=doc_conn)
                                action = result.get("action")

                            if action == "inserted":
                                inserted += 1
                                if lc == 0:
                                    no_links_inserted += 1
                                else:
                                    target_waiting_inserted += 1
                            elif action == "updated":
                                updated += 1
                                if lc == 0:
                                    no_links_updated += 1
                                else:
                                    target_waiting_updated += 1
                            elif action in ("skipped_already_active", "reused_existing_research"):
                                skipped_already_active += 1
                        except Exception as exc:
                            errors += 1
                            logger.exception("populate_all_eligible pid=%s: %s", pid, exc)
                    if not dry_run:
                        doc_conn.commit()
                except Exception:
                    if not dry_run:
                        doc_conn.rollback()
                    raise
                finally:
                    doc_conn.close()

                if max_total and (inserted + updated) >= max_total:
                    break
        finally:
            crm.close()

        return {
            "pipeline": PIPELINE_GENERATION,
            "ADMISSION_AUTHORITY_GATE": "ELIGIBLE_ONLY",
            "inserted": inserted,
            "updated": updated,
            "skipped_already_active": skipped_already_active,
            "skipped_out_of_target": skipped_out_of_target,
            "skipped_unknown_okpd": skipped_unknown_okpd,
            "target_waiting_inserted": target_waiting_inserted,
            "target_waiting_updated": target_waiting_updated,
            "no_links_inserted": no_links_inserted,
            "no_links_updated": no_links_updated,
            "errors": errors,
            "total_processed": inserted + updated + skipped_already_active + skipped_out_of_target + skipped_unknown_okpd + errors,
            "dry_run": dry_run,
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

        # Persisted scope authority is the single business admission source.
        # Missing authority is deliberately not recoverable from model output.
        if proc.get("admission_state") != "ELIGIBLE":
            return {
                "action": "analytics_only",
                "status": proc.get("admission_state") or "HOLD",
                "dispatchable": False,
                "reason": "SCOPE_AUTHORITY_NOT_ELIGIBLE",
                "procurement_id": procurement_id,
            }

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

        # Persisted business admission gates queue insertion; model signals only
        # determine ordering after the authority check above.

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
                "admission_state": proc.get("admission_state"),
                "admission_reason": proc.get("admission_reason"),
                "admission_policy_version": proc.get("admission_policy_version"),
                "admission_evaluated_at": (
                    proc["admission_evaluated_at"].isoformat()
                    if proc.get("admission_evaluated_at") is not None else None
                ),
                "authority_scope_version": proc.get("scope_version"),
                "procurement_scope_type": proc.get("procurement_scope_type"),
            },
            "candidate_level": decision.get("candidate_medal"),
            "candidate_score": None,
            "research_action": decision.get("research_action"),
            "research_depth": decision.get("research_depth"),
            "queue_lane": (
                "awarded_recent"
                if proc.get("source_lifecycle") == "AWARDED"
                else admission.research_lane or decision.get("queue_lane")
            ),
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
        status = "PRE_RESEARCH_WAITING"
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
                    SELECT p.id, p.source_table, p.source_id, p.contract_number, p.end_date,
                           p.auction_name, p.okpd_code, p.crm_stage, p.award_status,
                           a.procurement_scope_type, a.scope_confidence,
                           a.admission_state, a.admission_reason,
                           a.admission_policy_version, a.admission_evaluated_at,
                           a.scope_version, a.source_lifecycle
                    FROM crm_procurements p
                    LEFT JOIN crm_procurement_scope_authority a ON a.procurement_id = p.id
                    WHERE p.id = %s
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
                           sa.procurement_scope_type, sa.scope_confidence,
                           sa.admission_state, sa.admission_reason,
                           sa.admission_policy_version, sa.admission_evaluated_at,
                           sa.scope_version, sa.source_lifecycle,
                           p.ai_assessment_status
                    FROM procurement_ai_assessments a
                    JOIN crm_procurements p ON p.id = a.procurement_id
                    LEFT JOIN crm_procurement_scope_authority sa ON sa.procurement_id = p.id
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

    def _upsert_queue_task(self, task: Dict[str, Any], *, status: str = "PRE_RESEARCH_WAITING", last_error: Optional[str] = None, conn: Optional[Any] = None) -> Dict[str, Any]:
        sql_check = f"""
            SELECT q.id,
                   CASE
                       WHEN q.status = 'COMPLETED'
                        AND NOT EXISTS (
                            SELECT 1
                              FROM document_processing_results r2
                             WHERE r2.queue_id = q.id
                               AND r2.status = 'COMPLETED'
                        ) THEN 'PARTIAL'
                       ELSE q.status
                   END AS status,
                   q.research_depth,
                   EXISTS (
                       SELECT 1
                         FROM document_processing_results r
                        WHERE r.queue_id = q.id
                          AND r.status = 'COMPLETED'
                   ) AS successful_parse
             FROM document_processing_queue q
             WHERE {canonical_identity_sql("q")} = %s
                OR (q.contract_number IS NULL AND q.procurement_id = %s)
             ORDER BY successful_parse DESC, q.id
        """
        sql_insert = """
            INSERT INTO document_processing_queue
                (procurement_id, source_table, source_id, contract_number,
                 assessment_id, category_codes, category_context,
                 candidate_level, candidate_score,
                 research_action, research_depth,
                 queue_lane, priority_score,
                 status, pipeline_generation, last_error)
            VALUES
                (%s,%s,%s,%s, %s,%s,%s, %s,%s, %s,%s, %s,%s, %s,%s, %s)
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
                   last_error       = %s,
                   worker_id        = NULL,
                   started_at       = NULL,
                   completed_at     = NULL
             WHERE id = %s
        """
        should_close = False
        doc = conn
        if doc is None:
            doc = psycopg2.connect(**self._doc_dsn)
            doc.autocommit = False
            should_close = True
        try:
            with doc.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                identity = task.get("research_identity_key") or canonical_research_identity(
                    source_family=task["source_table"],
                    notice_number=task["contract_number"],
                    procurement_id=task["procurement_id"],
                ).key
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (identity,),
                )
                cur.execute(
                    sql_check,
                    (identity, task["procurement_id"]),
                )
                existing_rows = cur.fetchall()
                disposition = research_disposition(
                    existing_rows,
                    canonical_links_available=bool(task.get("category_context", {}).get("link_count")),
                )
                existing = existing_rows[0] if existing_rows else None
                if disposition == "REUSE_EXISTING_RESEARCH":
                    return {"action": "reused_existing_research", "queue_id": existing["id"], **task}
                if disposition in {
                    "DO_NOT_ENQUEUE_DUPLICATE_PROCESSING",
                    "DO_NOT_ENQUEUE_DUPLICATE_PENDING",
                    "DO_NOT_RETRY_NO_LINKS",
                }:
                    return {
                        "action": "skipped_already_active",
                        "queue_id": existing["id"] if existing else None,
                        "status": existing.get("status") if existing else None,
                        **task,
                    }

                if existing is not None and disposition == "RETRY_EXISTING_IDENTITY":
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
                            last_error,
                            existing["id"],
                        ),
                    )
                    if should_close:
                        doc.commit()
                    return {"action": "updated", "queue_id": existing["id"], "status": status, **task}

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
                        last_error,
                    ),
                )
                row = cur.fetchone()
                if should_close:
                    doc.commit()
                return {"action": "inserted", "queue_id": row["id"], "status": status, **task}
        except Exception:
            if should_close:
                doc.rollback()
            raise
        finally:
            if should_close:
                doc.close()
