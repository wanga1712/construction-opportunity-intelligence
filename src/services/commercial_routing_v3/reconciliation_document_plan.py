"""Prepare executable document plans for daily queue reconciliation."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

import psycopg2.extras

from src.services.commercial_routing_v3.document_links import (
    _should_skip_document_name,
    resolve_document_links,
)
from src.services.commercial_routing_v3.queue_plan_v2 import build_queue_plan_v2
from src.services.commercial_routing_v3.document_classifier_v1 import (
    classify_document_metadata,
)
from src.services.commercial_routing_v3.research_action_v2 import (
    decide_research_action,
)


_DOCS_SQL = """
    SELECT id, procurement_id, source_table, source_id, url, url_hash,
           file_name, physical_download_key, download_status,
           (local_path IS NOT NULL AND local_deleted_at IS NULL) AS has_local_file
      FROM document_files
     WHERE pipeline_generation = %s
       AND procurement_id = ANY(%s)
"""


def _planning_opportunities(
    procurement_id: int,
    source: dict,
    opportunities: list[dict],
) -> list[dict]:
    """Return real opportunities or one queue-only object-discovery context.

    The synthetic context is never persisted as a commercial category. It
    tells Queue V2 to select estimate/BOQ/NMCK documents and discover the
    category from parsed rows.
    """
    if opportunities:
        return [dict(row) for row in opportunities]
    return [
        {
            **dict(source),
            "procurement_id": procurement_id,
            "commercial_category_code": None,
            "category_code": None,
            "opportunity_track": "EMBEDDED_MATERIAL",
            "commercial_state": "OPEN",
            "research_action_v2": "DOCUMENT_RESEARCH_REQUIRED",
            "research_action_v2_base": "DOCUMENT_RESEARCH_REQUIRED",
            "planning_context_only": True,
        }
    ]


def _load_documents(cur: Any, generation: str, pids: list[int]) -> dict:
    if not pids:
        return {}
    cur.execute(_DOCS_SQL, (generation, pids))
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in cur.fetchall():
        grouped[int(row["procurement_id"])].append(dict(row))
    return grouped


def _promote_after_rate_only(cur: Any, pid: int, plan: dict, docs: list[dict]) -> bool:
    """Continue to other source files when a completed estimate has no volumes."""
    selected_ids = set(plan["selected_source_document_ids"])
    by_id = {int(doc["id"]): doc for doc in docs}
    if not selected_ids or not selected_ids.issubset(by_id):
        return False
    if any(by_id[doc_id].get("download_status") != "COMPLETED" for doc_id in selected_ids):
        return False
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE layout_status='UNIT_RATE_ONLY'
                                  AND unit_price_value IS NOT NULL) AS rate_rows,
               count(*) FILTER (WHERE quantity_value IS NOT NULL
                                  AND total_value IS NOT NULL) AS valued_rows
          FROM structured_estimate_rows
         WHERE procurement_id=%s
        """,
        (pid,),
    )
    counts = cur.fetchone()
    if not int(counts["rate_rows"] or 0) or int(counts["valued_rows"] or 0):
        return False
    additions: dict[int, dict] = {}
    for entry in plan["deferred_documents"]:
        doc_id = int(entry["source_document_id"])
        if doc_id not in by_id or doc_id in selected_ids:
            continue
        additions[doc_id] = {
            **entry,
            "selection_type": "FALLBACK",
            "selection_reason": "ESTIMATE_WITHOUT_CONFIRMED_VOLUME",
            "required_by_category": plan["category_codes"],
            "track": "EMBEDDED",
        }
    for doc_id, doc in by_id.items():
        name = str(doc.get("file_name") or "")
        classification = classify_document_metadata(name, source_table=doc.get("source_table"))
        if (
            doc_id in selected_ids or doc_id in additions
            or not classification.is_archive
            or "субподряд" not in name.lower()
        ):
            continue
        additions[doc_id] = {
            "source_document_id": doc_id,
            "file_name": name,
            "physical_key": doc.get("physical_download_key") or doc.get("url"),
            "document_class": classification.document_class.value,
            "selection_type": "SOFT_FALLBACK",
            "selection_reason": "ESTIMATE_WITHOUT_CONFIRMED_VOLUME_SUBCONTRACT_ARCHIVE",
            "category": plan["category_codes"][0],
            "track": "EMBEDDED",
            "required_by_category": plan["category_codes"],
            "required_facts": plan["required_facts"],
        }
    for doc_id, entry in sorted(additions.items())[:12]:
        plan["selected_documents"].append(entry)
        plan["selected_source_document_ids"].append(doc_id)
        plan["selected_physical_keys"].append(entry["physical_key"])
        key = (
            "soft_fallback_source_document_ids"
            if entry["selection_type"] == "SOFT_FALLBACK"
            else "fallback_source_document_ids"
        )
        plan[key].append(doc_id)
    return bool(additions)


def plan_queue_status(plan: dict) -> str:
    """Map an executable plan to a queue status that its claim gate can honor."""
    if (
        plan["selected_source_document_ids"]
        and plan["acquisition_allowed"]
        and plan["research_action_v2"]
        in {"DOCUMENT_RESEARCH_REQUIRED", "DOCUMENT_CONFIRMATION_REQUIRED"}
    ):
        return "PRE_RESEARCH_WAITING"
    if not plan["selected_source_document_ids"]:
        return "NO_LINKS"
    return "SKIPPED_NOT_TARGET"


def prepare_document_plans(
    cur: Any,
    *,
    generation: str,
    candidates: list[tuple[int, Any, str]],
    sources: dict[int, dict],
    opportunities: dict[int, list[dict]],
    apply: bool,
) -> tuple[dict[int, dict], dict[str, int]]:
    """Materialize missing canonical links, then build the normal queue plan."""
    pids = [pid for pid, _row, _reason in candidates]
    docs_by_pid = _load_documents(cur, generation, pids)
    planned_links = inserted_links = 0
    lookup_errors = 0
    for pid, row, _reason in candidates:
        # A NO_LINKS receipt is rechecked even when old non-researchable files
        # exist. Other candidates reuse the already materialized document set.
        if docs_by_pid.get(pid) and str((row or {}).get("status") or "") != "NO_LINKS":
            continue
        source = sources[pid]
        if not source.get("source_table") or source.get("source_id") is None:
            continue
        resolved = resolve_document_links(
            source_table=source["source_table"],
            source_id=source["source_id"],
            contract_number=source.get("contract_number"),
            limit=10000,
        )
        if resolved.get("error"):
            lookup_errors += 1
            raise RuntimeError(
                f"canonical document link lookup failed for procurement {pid}"
            )
        for link in resolved.get("links") or []:
            if _should_skip_document_name(link.get("document_name")):
                continue
            url = str(link.get("document_url") or "").strip()
            if not url:
                continue
            physical = str(link.get("physical_download_key") or url)
            if any(
                str(doc.get("physical_download_key") or "") == physical
                for doc in docs_by_pid.get(pid, ())
            ):
                continue
            planned_links += 1
            if not apply:
                continue
            cur.execute(
                """
                INSERT INTO document_files
                    (procurement_id, source_table, source_id, url, url_hash,
                     file_name, download_status, pipeline_generation,
                     canonical_source_document_id, physical_download_key,
                     created_at)
                VALUES (%s,%s,%s,%s,%s,%s,'PENDING',%s,%s,%s,NOW())
                ON CONFLICT DO NOTHING
                """,
                (
                    pid, source["source_table"], source["source_id"], url,
                    hashlib.sha256(url.encode("utf-8")).hexdigest(),
                    link.get("document_name") or "document", generation,
                    link.get("source_document_id"), physical,
                ),
            )
            inserted_links += int(cur.rowcount or 0)
    if apply and inserted_links:
        docs_by_pid = _load_documents(cur, generation, pids)

    plans: dict[int, dict] = {}
    expanded_rate_only = 0
    for pid in pids:
        docs = docs_by_pid.get(pid) or []
        opps = _planning_opportunities(
            pid,
            sources[pid],
            opportunities.get(pid) or [],
        )
        has_reusable = any(doc.get("has_local_file") for doc in docs)
        for opp in opps:
            decision = decide_research_action(
                category_code=opp.get("category_code"),
                opportunity_track=opp.get("opportunity_track"),
                commercial_state=opp.get("commercial_state"),
                candidate_medal=opp.get("candidate_initial_medal"),
                has_confirmed_facts=False,
                has_reusable_artifacts=has_reusable,
                window_closed=str(opp.get("commercial_state") or "").upper()
                in {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED"},
            )
            opp["research_action_v2"] = decision.action.value
        plans[pid] = build_queue_plan_v2(
            procurement=opps[0],
            opportunities=opps,
            documents=docs,
            pipeline_generation=generation,
        )
        if _promote_after_rate_only(cur, pid, plans[pid], docs):
            expanded_rate_only += 1
    return plans, {
        "planned_canonical_links": planned_links,
        "inserted_canonical_links": inserted_links,
        "canonical_lookup_errors": lookup_errors,
        "plans_built": len(plans),
        "expanded_after_rate_only": expanded_rate_only,
    }
