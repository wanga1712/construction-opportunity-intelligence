"""Asynchronous worker service for document match context validation.

Claims raw candidate matches, enriches them with factual procurement data
and CRM taxonomy, filters to canonical TARGET OKPD procurements, validates
them with ContextValidator, updates validation status in document_match_details,
and rebuilds document_evidence for affected procurements.

Fail-closed:
- Only CONFIRMED details can produce positive document_evidence.
- Qwen outages do not break document processing (candidates remain UNKNOWN).
- Out-of-target procurements are excluded from normal service validation.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

try:
    from tender_documents_research.document_processor.context_validator import ContextValidator
    from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader, TaxonomySnapshot
except ImportError:
    from document_processor.context_validator import ContextValidator
    from document_processor.crm_taxonomy_loader import CrmTaxonomyLoader, TaxonomySnapshot
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

load_dotenv("/opt/CRM_Streamlit/.env")

logger = logging.getLogger("document_processor.context_validator_service")
PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"

DEFAULT_TARGET_REFRESH_SECONDS = 60.0
_TARGET_IDS_CACHE: Dict[str, Any] = {"ids": None, "refreshed_at": 0.0}


def get_target_procurement_ids(
    crm_conn,
    priors: List[Dict[str, Any]],
) -> List[int]:
    """Retrieves list of active TARGET procurement IDs from CRM database.

    Uses distinct OKPD classification optimization for high efficiency across 160k+ procurements.
    Handles both dict and tuple cursors safely.
    """
    with crm_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT okpd_code FROM crm_procurements WHERE okpd_code IS NOT NULL AND okpd_code != ''")
        rows = cur.fetchall()
        distinct_okpds = [r[0] if isinstance(r, (list, tuple)) else r["okpd_code"] for r in rows if r]

    target_okpds = [okpd for okpd in distinct_okpds if classify_target_okpd(okpd, priors)[0] == ADMISSION_TARGET]
    if not target_okpds:
        return []

    with crm_conn.cursor() as cur:
        cur.execute("SELECT id FROM crm_procurements WHERE okpd_code = ANY(%s)", (target_okpds,))
        rows = cur.fetchall()
        return sorted([r[0] if isinstance(r, (list, tuple)) else r["id"] for r in rows if r])


def get_cached_target_procurement_ids(
    crm_conn,
    priors: List[Dict[str, Any]],
    refresh_interval: float = DEFAULT_TARGET_REFRESH_SECONDS,
    force_refresh: bool = False,
) -> List[int]:
    """Gets cached target procurement IDs, refreshing from CRM DB if stale."""
    now = time.time()
    if (
        force_refresh
        or _TARGET_IDS_CACHE["ids"] is None
        or (now - _TARGET_IDS_CACHE["refreshed_at"]) >= refresh_interval
    ):
        ids = get_target_procurement_ids(crm_conn, priors)
        _TARGET_IDS_CACHE["ids"] = ids
        _TARGET_IDS_CACHE["refreshed_at"] = now
        logger.info("Refreshed target procurement IDs cache: %d target IDs", len(ids))
    return _TARGET_IDS_CACHE["ids"]



def get_doc_db_connection():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def get_crm_db_connection():
    return psycopg2.connect(**require_crm_db_connect_kwargs())


def claim_unvalidated_candidates(
    conn,
    *,
    batch_size: int = 50,
    target_procurement_ids: Optional[List[int]] = None,
    generation: str = PIPELINE_GENERATION,
) -> List[Dict[str, Any]]:
    """Claims a batch of candidates for validation with correct SQL precedence.

    TARGET restriction is applied BEFORE ORDER BY and LIMIT.
    - None: claims candidates across all procurements (diagnostic/tests).
    - []: claims ZERO candidates (returns [] immediately).
    - [...]: adds SQL predicate `AND d.procurement_id = ANY(%s)`.
    """
    if target_procurement_ids is not None and len(target_procurement_ids) == 0:
        return []

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        query = """
            SELECT d.id, d.id as detail_id, d.match_id, d.procurement_id, d.category_code, d.subcategory_code,
                   d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
                   d.context_before, d.context_after, d.match_method,
                   m.document_name, m.archive_member_path
            FROM document_match_details d
            JOIN document_matches m ON d.match_id = m.id
            WHERE (
                d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING')
                OR d.validation_status IS NULL
            )
            AND d.pipeline_generation = %s
        """
        params: List[Any] = [generation]
        if target_procurement_ids is not None:
            query += " AND d.procurement_id = ANY(%s)"
            params.append(target_procurement_ids)

        query += " ORDER BY d.id ASC LIMIT %s FOR UPDATE OF d SKIP LOCKED"
        params.append(batch_size)

        cur.execute(query, tuple(params))
        return cur.fetchall()


def enrich_candidates_with_crm_facts(
    candidates: List[Dict[str, Any]],
    crm_conn,
    taxonomy_snapshot: Optional[TaxonomySnapshot] = None,
) -> List[Dict[str, Any]]:
    """Enriches claimed candidates with factual procurement data and canonical CRM taxonomy."""
    if not candidates:
        return []

    if taxonomy_snapshot is None:
        taxonomy_snapshot = CrmTaxonomyLoader().load_snapshot()

    pids = list({c["procurement_id"] for c in candidates if c.get("procurement_id")})
    proc_map: Dict[int, Dict[str, Any]] = {}

    if pids:
        with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, auction_name, okpd_code, okpd_name
                FROM crm_procurements
                WHERE id = ANY(%s)
            """, (pids,))
            for row in cur.fetchall():
                proc_map[row["id"]] = dict(row)

    enriched: List[Dict[str, Any]] = []
    for c in candidates:
        item = dict(c)
        pid = item.get("procurement_id")
        p_data = proc_map.get(pid, {})

        item["procurement_title"] = p_data.get("auction_name") or ""
        item["procurement_okpd_code"] = p_data.get("okpd_code") or ""
        item["procurement_okpd_name"] = p_data.get("okpd_name") or ""

        cat_code = item.get("category_code") or ""
        sub_code = item.get("subcategory_code") or ""

        cat_data = taxonomy_snapshot.categories.get(cat_code, {})
        item["category_name"] = cat_data.get("category_name") or cat_code

        subcategories = cat_data.get("subcategories", {})
        sub_obj = subcategories.get(sub_code)
        if sub_obj:
            item["subcategory_name"] = sub_obj.subcategory_name
            item["negative_phrases"] = list(sub_obj.negative_phrases)
        else:
            item["subcategory_name"] = sub_code
            item["negative_phrases"] = []

        enriched.append(item)

    return enriched


def filter_target_candidates(
    candidates: List[Dict[str, Any]],
    priors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Normal validator processes ONLY TARGET procurements using canonical classify_target_okpd."""
    target_candidates = []
    for c in candidates:
        okpd = c.get("procurement_okpd_code")
        status, _ = classify_target_okpd(okpd, priors)
        if status == ADMISSION_TARGET:
            target_candidates.append(c)
    return target_candidates


def update_candidate_validations(conn, results: List[Dict[str, Any]]) -> Set[Tuple[int, str]]:
    """Updates document_match_details with validation outcomes.

    Strict provenance enforcement: CONFIRMED results missing explicit validator provenance
    are demoted to UNKNOWN to prevent fake v1/v2 evidence creation.
    """
    affected: Set[Tuple[int, str]] = set()
    if not results:
        return affected

    with conn.cursor() as cur:
        for r in results:
            detail_id = r["detail_id"]
            status = r["decision"]
            method = r.get("validation_method")
            val_name = r.get("validator_name")
            val_ver = r.get("validator_version")

            if status == "CONFIRMED" and (not val_name or not val_ver or not method):
                status = "UNKNOWN"
                reason = "[MISSING_VALIDATOR_PROVENANCE] Missing explicit validator provenance attributes"
                method = "UNSPECIFIED"
                val_name = "context_validator"
                val_ver = "UNKNOWN"
            else:
                method = method or "QWEN_CONTEXT_V2"
                val_name = val_name or "context_validator"
                val_ver = val_ver or "v2"
                reason = f"[{r.get('reason_code', 'UNSPECIFIED')}] {r.get('reason', '')}"

            cur.execute("""
                UPDATE document_match_details
                SET validation_status = %s,
                    validation_method = %s,
                    validation_reason = %s,
                    validated_at = NOW(),
                    validator_name = %s,
                    validator_version = %s
                WHERE id = %s
            """, (status, method, reason, val_name, val_ver, detail_id))

            affected.add((r["procurement_id"], r["category_code"]))

    conn.commit()
    return affected


def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
    """Rebuilds document_evidence ONLY for affected procurement/category pairs.

    Truthful evidence provenance policy (R3-4E-A):
    - If current v2 CONFIRMED details exist:
      Build document_evidence strictly from v2 CONFIRMED details.
      match_count = len(v2_rows)
      evidence_score = max(score for r in v2_rows)
      validation_version = "v2"
      validation_method = "QWEN_CONTEXT_V2"
      Legacy v1 rows remain stored in document_match_details but do NOT contribute to v2 score/count.
    - Else if legacy v1 CONFIRMED details exist:
      Build document_evidence strictly from v1 CONFIRMED details.
      match_count = len(v1_rows)
      evidence_score = max(score for r in v1_rows)
      validation_version = "v1"
      validation_method = "QWEN_CONTEXT_V1"
    - Else (0 confirmed details):
      DELETE from document_evidence.
    """
    if not affected:
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected:
            cur.execute("""
                SELECT d.score, m.queue_id, d.validator_version, d.validation_method
                FROM document_match_details d
                JOIN document_matches m ON d.match_id = m.id
                WHERE d.procurement_id = %s
                  AND d.category_code = %s
                  AND d.pipeline_generation = %s
                  AND d.validation_status = 'CONFIRMED'
            """, (pid, cat, PIPELINE_GENERATION))
            confirmed_rows = cur.fetchall()

            if not confirmed_rows:
                cur.execute("""
                    DELETE FROM document_evidence
                    WHERE procurement_id = %s
                      AND category_code = %s
                      AND pipeline_generation = %s
                """, (pid, cat, PIPELINE_GENERATION))
                continue

            # Explicit provenance check for v2 confirmed rows
            v2_rows = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v2"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V2"
            ]

            if v2_rows:
                target_rows = v2_rows
                val_ver = "v2"
                val_method = "QWEN_CONTEXT_V2"
            else:
                target_rows = confirmed_rows
                val_ver = "v1"
                val_method = "QWEN_CONTEXT_V1"

            max_score = max(float(r["score"]) for r in target_rows)
            match_count = len(target_rows)
            queue_id = target_rows[0]["queue_id"]

            cur.execute("""
                INSERT INTO document_evidence
                (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (procurement_id, category_code, pipeline_generation)
                DO UPDATE SET
                    evidence_score = EXCLUDED.evidence_score,
                    match_count = EXCLUDED.match_count,
                    validation_status = 'CONFIRMED',
                    validation_version = EXCLUDED.validation_version,
                    validation_method = EXCLUDED.validation_method
            """, (
                pid, queue_id, cat, max_score, match_count,
                "STRUCTURED_EXTRACTION_PENDING", "CONFIRMED", val_ver, val_method,
                PIPELINE_GENERATION
            ))

    conn.commit()


def process_batch(
    doc_conn,
    crm_conn,
    validator: ContextValidator,
    priors: List[Dict[str, Any]],
    taxonomy_snapshot: TaxonomySnapshot,
    *,
    batch_size: int = 50,
    target_procurement_ids: Optional[List[int]] = None,
    refresh_interval: float = DEFAULT_TARGET_REFRESH_SECONDS,
    use_target_cache: bool = True,
) -> int:
    """Processes a single batch of unvalidated candidates.

    When target_procurement_ids is None and use_target_cache is True (normal daemon usage),
    automatically fetches and uses cached target procurement IDs from CRM DB (refreshed every 60s).
    """
    if target_procurement_ids is None and use_target_cache:
        effective_target_ids = get_cached_target_procurement_ids(
            crm_conn, priors, refresh_interval=refresh_interval
        )
    else:
        effective_target_ids = target_procurement_ids

    candidates = claim_unvalidated_candidates(
        doc_conn, batch_size=batch_size, target_procurement_ids=effective_target_ids
    )
    if not candidates:
        return 0

    enriched = enrich_candidates_with_crm_facts(candidates, crm_conn, taxonomy_snapshot)
    target_candidates = filter_target_candidates(enriched, priors)

    stale_filtered = len(enriched) - len(target_candidates)
    if stale_filtered > 0:
        logger.warning(
            "Detected %d stale claimed candidates (out-of-target); force-refreshing target ID cache",
            stale_filtered,
        )
        if target_procurement_ids is None and use_target_cache:
            get_cached_target_procurement_ids(crm_conn, priors, force_refresh=True)

    if not target_candidates:
        return 0

    results = validator.validate_candidates(target_candidates)
    affected = update_candidate_validations(doc_conn, results)
    rebuild_affected_evidence(doc_conn, affected)
    logger.info(
        "Processed batch: claimed=%d, target_validated=%d, stale_filtered=%d",
        len(candidates),
        len(results),
        stale_filtered,
    )
    return len(results)


def main():
    """Main daemon entrypoint."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Starting CRM V3 Context Validator Daemon...")

    validator = ContextValidator()
    doc_conn = get_doc_db_connection()
    crm_conn = get_crm_db_connection()

    class _CrmDbWrapper:
        def __init__(self, conn):
            self.conn = conn
        def execute_query(self, sql):
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                return cur.fetchall()

    priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
    taxonomy_snapshot = CrmTaxonomyLoader().load_snapshot()
    logger.info("Loaded %d OKPD priors and %d categories", len(priors), len(taxonomy_snapshot.categories))

    while True:
        try:
            count = process_batch(
                doc_conn,
                crm_conn,
                validator,
                priors,
                taxonomy_snapshot,
                batch_size=20,
            )
            if count == 0:
                time.sleep(3.0)
            else:
                logger.info("Validated batch of %d TARGET candidates", count)
        except Exception as exc:
            logger.error("Error in validator daemon loop: %s", exc)
            time.sleep(5.0)


if __name__ == "__main__":
    main()
