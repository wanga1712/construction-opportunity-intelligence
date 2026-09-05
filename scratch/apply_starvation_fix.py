#!/usr/bin/env python3
"""
Applies target claim starvation fix to context_validator_service.py.
"""
import os
import re

SERVICE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

with open(SERVICE_PATH, "r", encoding="utf-8") as f:
    src = f.read()

# 1. Add DEFAULT_TARGET_REFRESH_SECONDS and cache variable after PIPELINE_GENERATION
cache_code = '''
DEFAULT_TARGET_REFRESH_SECONDS = 60.0
_TARGET_IDS_CACHE: Dict[str, Any] = {"ids": None, "refreshed_at": 0.0}


def get_target_procurement_ids(
    crm_conn,
    priors: List[Dict[str, Any]],
) -> List[int]:
    """Retrieves list of active TARGET procurement IDs from CRM database.

    Uses distinct OKPD classification optimization for high efficiency across 160k+ procurements.
    """
    with crm_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT okpd_code FROM crm_procurements WHERE okpd_code IS NOT NULL AND okpd_code != ''")
        distinct_okpds = [r[0] for r in cur.fetchall()]

    target_okpds = [okpd for okpd in distinct_okpds if classify_target_okpd(okpd, priors)[0] == ADMISSION_TARGET]
    if not target_okpds:
        return []

    with crm_conn.cursor() as cur:
        cur.execute("SELECT id FROM crm_procurements WHERE okpd_code = ANY(%s)", (target_okpds,))
        return sorted([r[0] for r in cur.fetchall()])


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
'''

# Find insertion point after PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"
gen_marker = 'PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"'
assert gen_marker in src, "PIPELINE_GENERATION not found"
src = src.replace(gen_marker, gen_marker + "\n" + cache_code, 1)

# 2. Replace claim_unvalidated_candidates
old_claim = '''def claim_unvalidated_candidates(
    conn,
    *,
    batch_size: int = 50,
    target_procurement_ids: Optional[List[int]] = None,
    generation: str = PIPELINE_GENERATION,
) -> List[Dict[str, Any]]:
    """Claims a batch of candidates for validation with correct SQL precedence."""
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
        if target_procurement_ids:
            query += " AND d.procurement_id = ANY(%s)"
            params.append(target_procurement_ids)

        query += " ORDER BY d.id ASC LIMIT %s FOR UPDATE OF d SKIP LOCKED"
        params.append(batch_size)

        cur.execute(query, tuple(params))
        return cur.fetchall()'''

new_claim = '''def claim_unvalidated_candidates(
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
        return cur.fetchall()'''

assert old_claim in src, "old claim_unvalidated_candidates not found"
src = src.replace(old_claim, new_claim, 1)

# 3. Replace process_batch
old_process_batch = '''def process_batch(
    doc_conn,
    crm_conn,
    validator: ContextValidator,
    priors: List[Dict[str, Any]],
    taxonomy_snapshot: TaxonomySnapshot,
    *,
    batch_size: int = 50,
    target_procurement_ids: Optional[List[int]] = None,
) -> int:
    """Processes a single batch of unvalidated candidates."""
    candidates = claim_unvalidated_candidates(
        doc_conn, batch_size=batch_size, target_procurement_ids=target_procurement_ids
    )
    if not candidates:
        return 0

    enriched = enrich_candidates_with_crm_facts(candidates, crm_conn, taxonomy_snapshot)
    target_candidates = filter_target_candidates(enriched, priors)
    if not target_candidates:
        return 0

    results = validator.validate_candidates(target_candidates)
    affected = update_candidate_validations(doc_conn, results)
    rebuild_affected_evidence(doc_conn, affected)
    return len(results)'''

new_process_batch = '''def process_batch(
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
    return len(results)'''

assert old_process_batch in src, "old process_batch not found"
src = src.replace(old_process_batch, new_process_batch, 1)

with open(SERVICE_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Applied target claim starvation fix to context_validator_service.py")
