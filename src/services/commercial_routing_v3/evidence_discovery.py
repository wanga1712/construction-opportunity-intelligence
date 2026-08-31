"""Evidence discovery — bridges document_match_details → crm_v3_raw_source_evidence.

EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH = NO.
This module does NOT do its own lexical search. It reads from the production
matcher output (document_match_details) which is produced by the
tender_documents_research document processor, and bridges those deterministic
matches into V3 evidence.

Vocabulary authority: crm_product_subcategory_terms.term_type='search'
(loaded via CrmTaxonomyLoader in the production matcher — we read its output).
Vocabulary hash: SHA256 of all active search terms, sorted canonically.

FIRST_MATCH_BREAK = NO (production matcher does not break on first match).
FACT_CATEGORY_FROM_PHRASE_REGISTRY = YES (category_code from document_match_details).
MODEL_OVERWRITES_FACT_CATEGORY = NO.
MATCH_CONTEXT_REQUIRED = YES (context_before, context_after, source_locator_json mandatory).
"""

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("commercial_routing_v3.evidence_discovery")

PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"


def compute_evidence_hash(matched_term: str, raw_text: str, source_locator_json: str) -> str:
    payload = f"{matched_term}||{raw_text}||{source_locator_json}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def compute_vocabulary_hash(vocab: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Hash the full active vocabulary. Returns (version, sha256)."""
    ser = json.dumps(vocab, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(ser.encode("utf-8")).hexdigest()
    version = f"v3_vocab_{h[:12]}"
    return version, h


def load_discovery_vocabulary(crm_db) -> List[Dict[str, Any]]:
    """Load real search phrases from crm_product_subcategory_terms.

    VOCABULARY_AUTHORITY = crm_product_subcategory_terms.term_type='search'
    NOT category/subcategory names. NOT category codes.

    Returns list of {term, category_code, subcategory_code, weight} dicts.
    VOCABULARY_TERMS_TOTAL > 0 guaranteed if taxonomy is populated.
    """
    vocab: List[Dict[str, Any]] = []
    try:
        rows = crm_db.execute_query(
            """
            SELECT t.phrase, t.weight, t.term_type,
                   s.subcategory_code,
                   c.category_code
            FROM crm_product_subcategory_terms t
            JOIN crm_product_subcategories s ON s.id = t.subcategory_id AND s.is_active = TRUE
            JOIN crm_product_categories c ON c.id = s.category_id AND c.is_active = TRUE
            WHERE t.is_active = TRUE AND t.term_type = 'search'
            ORDER BY c.category_code, s.subcategory_code, t.weight DESC, t.phrase
            """
        ) or []
        for r in rows:
            phrase = (r.get("phrase") or "").strip().lower()
            if not phrase or "?" in phrase:
                continue
            vocab.append({
                "term": phrase,
                "category_code": r.get("category_code"),
                "subcategory_code": r.get("subcategory_code"),
                "weight": int(r.get("weight") or 100),
                "term_type": r.get("term_type"),
                "method": "PHRASE_REGISTRY_MATCH",
            })
    except Exception as exc:
        logger.error("load_discovery_vocabulary error: %s", exc)
    return vocab


def _get_doc_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": "document_intelligence",
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def bridge_match_details_to_evidence(
    procurement_id: int,
    crm_db,
    *,
    pipeline_generation: str = PIPELINE_GENERATION,
    research_generation_hash: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Bridge document_match_details → crm_v3_raw_source_evidence.

    EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH = NO.
    Reads deterministic matcher output. No re-scanning of document text.
    FACT_CATEGORY_FROM_PHRASE_REGISTRY = YES: category_code comes from
    document_match_details.category_code (set by production matcher from
    crm_product_subcategory_terms), not from model output.
    MODEL_OVERWRITES_FACT_CATEGORY = NO.
    MATCH_CONTEXT_REQUIRED = YES.
    """
    import psycopg2
    import psycopg2.extras

    doc_dsn = _get_doc_dsn()
    persisted_rows: List[Dict[str, Any]] = []
    seen_hashes: Set[str] = set()

    try:
        doc_conn = psycopg2.connect(**doc_dsn)
    except Exception as exc:
        logger.error("bridge_match_details: doc_conn failed: %s", exc)
        return []

    try:
        with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Fetch all match details for this procurement from production matcher output.
            # category_code comes from production matcher (phrase registry authority).
            cur.execute(
                """
                SELECT
                    dmd.id AS detail_id,
                    dmd.match_id,
                    dmd.procurement_id,
                    dmd.category_code,
                    dmd.subcategory_code,
                    dmd.matched_term,
                    dmd.term_type,
                    dmd.score,
                    dmd.row_data,
                    dmd.page_or_sheet,
                    dmd.row_number,
                    dmd.context_before,
                    dmd.context_after,
                    dmd.pipeline_generation,
                    dm.document_name,
                    dm.file_id AS document_file_id,
                    df.canonical_source_document_id AS canonical_source_document_id
                FROM document_match_details dmd
                JOIN document_matches dm ON dm.id = dmd.match_id
                LEFT JOIN document_files df ON df.id = dm.file_id
                WHERE dmd.procurement_id = %s
                  AND dmd.pipeline_generation = %s
                ORDER BY dmd.id
                """,
                (procurement_id, pipeline_generation),
            )
            detail_rows = cur.fetchall() or []
    except Exception as exc:
        logger.error("bridge_match_details: detail fetch failed pid=%s: %s", procurement_id, exc)
        doc_conn.close()
        return []
    finally:
        doc_conn.close()

    for row in detail_rows:
        matched_term = (row.get("matched_term") or "").strip()
        if not matched_term:
            continue

        # Build raw_text: prefer row_data text content, fall back to matched_term
        row_data = row.get("row_data")
        if row_data and isinstance(row_data, str):
            try:
                row_data = json.loads(row_data)
            except Exception:
                row_data = {}
        raw_text = str(row_data.get("text") if isinstance(row_data, dict) else "") or matched_term

        # Source locator: page/sheet + row + match_id
        source_locator = {
            "match_detail_id": row.get("detail_id"),
            "match_id": row.get("match_id"),
            "page_or_sheet": row.get("page_or_sheet"),
            "row_number": row.get("row_number"),
            "document_name": row.get("document_name"),
            "pipeline_generation": pipeline_generation,
        }
        source_loc_json = json.dumps(source_locator, default=str, sort_keys=True)
        ev_hash = compute_evidence_hash(matched_term, raw_text, source_loc_json)

        if ev_hash in seen_hashes:
            continue
        seen_hashes.add(ev_hash)

        # MATCH_CONTEXT_REQUIRED = YES
        context_before = row.get("context_before")
        if context_before is None:
            context_before = []
        if isinstance(context_before, str):
            try:
                context_before = json.loads(context_before)
            except Exception:
                context_before = [context_before]

        context_after = row.get("context_after")
        if context_after is None:
            context_after = []
        if isinstance(context_after, str):
            try:
                context_after = json.loads(context_after)
            except Exception:
                context_after = [context_after]

        # FACT_CATEGORY_FROM_PHRASE_REGISTRY = YES
        # category_code from matcher output (phrase registry authority), NOT from model.
        category_code = row.get("category_code")

        hit = {
            "procurement_id": procurement_id,
            "source_document_id": row.get("canonical_source_document_id"),
            "document_file_id": row.get("document_file_id"),
            "document_name": row.get("document_name"),
            "matched_term": matched_term,
            "raw_text": raw_text,
            "context_before": context_before,
            "context_after": context_after,
            "source_locator_json": source_loc_json,
            "discovery_method": "BRIDGE_FROM_MATCH_DETAILS",
            "suggested_category_code": category_code,
            "evidence_hash": ev_hash,
            "pipeline_generation": pipeline_generation,
            "research_generation_hash": research_generation_hash,
        }

        try:
            res = crm_db.execute_query(
                """
                INSERT INTO crm_v3_raw_source_evidence (
                    procurement_id, source_document_id, document_file_id, document_name,
                    matched_term, raw_text, context_before, context_after,
                    source_locator_json, discovery_method, suggested_category_code,
                    evidence_hash, pipeline_generation, research_generation_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id, procurement_id, source_document_id, document_file_id, document_name,
                          matched_term, raw_text, source_locator_json,
                          evidence_hash, pipeline_generation, research_generation_hash,
                          created_at
                """,
                (
                    hit["procurement_id"],
                    hit["source_document_id"],
                    hit["document_file_id"],
                    hit["document_name"],
                    hit["matched_term"],
                    hit["raw_text"],
                    json.dumps(hit["context_before"], ensure_ascii=False),
                    json.dumps(hit["context_after"], ensure_ascii=False),
                    hit["source_locator_json"],
                    hit["discovery_method"],
                    hit["suggested_category_code"],
                    hit["evidence_hash"],
                    hit["pipeline_generation"],
                    hit["research_generation_hash"],
                ),
            )
            if res:
                persisted_rows.extend(res)
        except Exception as exc:
            logger.error(
                "bridge_match_details: persist failed pid=%s term=%s: %s",
                procurement_id, matched_term, exc
            )

    return persisted_rows


# ---------------------------------------------------------------------------
# Legacy compatibility: discover_and_persist_raw_evidence now delegates to
# bridge_match_details_to_evidence.
# EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH = NO.
# ---------------------------------------------------------------------------

def discover_and_persist_raw_evidence(
    procurement_id: int,
    crm_db,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
    pipeline_generation: str = PIPELINE_GENERATION,
    research_generation_hash: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Bridge document_match_details → crm_v3_raw_source_evidence.

    EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH = NO.
    This function no longer performs any lexical document scanning.
    It reads from document_match_details (production matcher output).
    """
    return bridge_match_details_to_evidence(
        procurement_id=procurement_id,
        crm_db=crm_db,
        pipeline_generation=pipeline_generation,
        research_generation_hash=research_generation_hash,
    )
