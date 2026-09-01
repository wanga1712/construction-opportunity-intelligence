"""
R4 Input Selector Authority Module.
Provides deterministic selection of trusted V4 CONFIRMED candidate details
from PostgreSQL document_intelligence DB to serve as R4 structured extraction inputs.

Reuses the accepted public R3 documentary hydration semantics:
build_source_document_context(candidate) from context_validator.py.
"""

import hashlib
import psycopg2.extras
from typing import Any, Dict, List, Optional, Tuple

from tender_documents_research.document_processor.context_validator import (
    build_source_document_context,
)

R4_INPUT_AUTHORITY = "TRUSTED_V4_CONFIRMED_DETAIL"

def build_r4_source_snapshot(candidate: Dict[str, Any]) -> str:
    """
    Builds the pure documentary source text snapshot for an R4 candidate detail.
    Reuses accepted R3 build_source_document_context(candidate).
    
    Guarantees:
    - GENERATED_SOURCE_PLACEHOLDER = NONE (Returns "" if no documentary text exists)
    - MATCHED_TERM_METADATA_AS_SOURCE = NO (matched_term metadata alone is NOT source text)
    - SOURCE_METADATA_LEAKS = 0 (No titles, categories, OKPD, or prompt text)
    """
    # Reuse R3 accepted documentary hydration
    raw_context = build_source_document_context(candidate)
    snapshot = raw_context.strip() if raw_context else ""
    return snapshot

# Alias for backward compatibility
build_source_text_snapshot = build_r4_source_snapshot

def get_r4_input_candidates(conn, category_code: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Selects trusted V4 CONFIRMED candidate details for R4 structured fact extraction.
    
    Authority:
    document_match_details d JOIN document_matches m ON m.id = d.match_id
    WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND d.validation_status = 'CONFIRMED'
      AND d.validator_name = 'context_validator'
      AND LOWER(d.validator_version) = 'v4'
      AND UPPER(d.validation_method) = 'QWEN_CONTEXT_V4'
    """
    sql = """
        SELECT
            d.id AS detail_id,
            d.match_id,
            d.procurement_id,
            m.queue_id,
            d.category_code,
            d.subcategory_code,
            m.document_name,
            m.archive_member_path,
            d.page_or_sheet,
            d.row_number,
            d.matched_term,
            d.context_before,
            d.context_after,
            d.row_data,
            d.validation_status,
            d.validator_name AS source_validator_name,
            d.validator_version AS source_validator_version,
            d.validation_method AS source_validation_method,
            d.validated_at
        FROM document_match_details d
        JOIN document_matches m ON m.id = d.match_id
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.validation_status = 'CONFIRMED'
          AND d.validator_name = 'context_validator'
          AND LOWER(d.validator_version) = 'v4'
          AND UPPER(d.validation_method) = 'QWEN_CONTEXT_V4'
    """
    params: List[Any] = []
    if category_code:
        sql += " AND d.category_code = %s"
        params.append(category_code)
    
    sql += " ORDER BY d.id ASC"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]

    for r in rows:
        snapshot = build_r4_source_snapshot(r)
        r["source_text_snapshot"] = snapshot
        r["source_text_sha256"] = hashlib.sha256(snapshot.encode("utf-8")).hexdigest() if snapshot else ""
        r["source_available"] = bool(snapshot)
        r["extraction_eligible"] = bool(r["validation_status"] == "CONFIRMED" and snapshot)

    return rows
