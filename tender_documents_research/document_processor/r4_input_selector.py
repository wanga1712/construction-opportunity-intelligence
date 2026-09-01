"""
R4 Input Selector Authority Module.
Provides deterministic selection of trusted V4 CONFIRMED candidate details
from PostgreSQL document_intelligence DB to serve as R4 structured extraction inputs.
"""

import json
import hashlib
import psycopg2.extras
from typing import Any, Dict, List, Optional

R4_INPUT_AUTHORITY = "TRUSTED_V4_CONFIRMED_DETAIL"

def build_source_text_snapshot(candidate: Dict[str, Any]) -> str:
    """
    Builds the documentary source text snapshot for a candidate detail.
    Contains strictly documentary source text, without title or category metadata.
    """
    row_data = candidate.get("row_data")
    if row_data:
        if isinstance(row_data, dict):
            # Extract values from row dict if present
            vals = [str(v).strip() for v in row_data.values() if v]
            if vals:
                return " | ".join(vals)
        elif isinstance(row_data, str) and row_data.strip():
            return row_data.strip()
    
    before = (candidate.get("context_before") or "").strip() if isinstance(candidate.get("context_before"), str) else ""
    term = (candidate.get("matched_term") or "").strip() if isinstance(candidate.get("matched_term"), str) else ""
    after = (candidate.get("context_after") or "").strip() if isinstance(candidate.get("context_after"), str) else ""
    
    parts = [p for p in [before, term, after] if p]
    if parts:
        return " ".join(parts)
    
    return term or "DOCUMENTARY_SOURCE_SNAPSHOT"

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
        snapshot = build_source_text_snapshot(r)
        r["source_text_snapshot"] = snapshot
        r["source_text_sha256"] = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()

    return rows
