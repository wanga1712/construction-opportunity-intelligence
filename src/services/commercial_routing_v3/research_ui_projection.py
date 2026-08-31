"""Read-only research UI projection service for CRM V3.

Provides bulk loading of current-generation factual document research state,
summary metrics, category lists, top matched terms, and per-document raw evidence.
Strictly queries document_intelligence DB for queue/files/results,
and canonical crm_app DB for CRM evidence/truth/snapshots.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import json
import logging
import os
import psycopg2
import psycopg2.extras

from src.services.commercial_routing_v3.card_research_state import _get_doc_db_conn

logger = logging.getLogger(__name__)

PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"

@dataclass
class ResearchUiProjection:
    procurement_id: int
    research_generation_hash: Optional[str] = None
    research_state: str = "WAITING_RESEARCH"  # WAITING_RESEARCH, RESEARCHING, EVIDENCE_FOUND, NO_EVIDENCE, PARTIAL, FAILED, PROJECTION_ERROR

    documents_total: int = 0
    documents_researched: int = 0
    documents_remaining: int = 0

    documents_with_evidence: int = 0
    documents_no_evidence: int = 0
    documents_unknown: int = 0

    evidence_count: int = 0

    category_codes: List[str] = field(default_factory=list)
    category_names: List[str] = field(default_factory=list)

    top_matched_terms: List[str] = field(default_factory=list)

    started_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    completed_at: Optional[str] = None

    truth_completeness: Optional[str] = None
    error_detail: Optional[str] = None

def format_friendly_locator(locator_data: Any) -> str:
    if not locator_data:
        return ""
    if isinstance(locator_data, str):
        try:
            locator_data = json.loads(locator_data)
        except Exception:
            return locator_data

    if not isinstance(locator_data, dict):
        return str(locator_data)

    parts = []
    archive = locator_data.get("archive_member_path") or locator_data.get("archive")
    if archive:
        parts.append(f"файл в архиве: {archive}")

    sheet = locator_data.get("sheet_name") or locator_data.get("sheet")
    row = locator_data.get("row_number") or locator_data.get("row")
    if sheet:
        if row is not None:
            parts.append(f"лист «{sheet}», строка {row}")
        else:
            parts.append(f"лист «{sheet}»")
    elif row is not None:
        parts.append(f"строка {row}")

    page = locator_data.get("page_number") or locator_data.get("page")
    if page is not None:
        parts.append(f"стр. {page}")

    para = locator_data.get("paragraph_index") or locator_data.get("paragraph")
    if para is not None:
        parts.append(f"абзац {para}")

    pos = locator_data.get("position_number") or locator_data.get("position")
    if pos is not None:
        parts.append(f"позиция {pos}")

    return ", ".join(parts) if parts else ""

def _get_crm_db_conn():
    from dotenv import load_dotenv
    try:
        load_dotenv("/opt/CRM_Streamlit/.env", override=True)
    except Exception:
        pass
    try:
        load_dotenv("/etc/crm_v3.env", override=True)
    except Exception:
        pass
    host = os.getenv("CRM_DB_HOST") or "127.0.0.1"
    port = int(os.getenv("CRM_DB_PORT") or "5432")
    user = os.getenv("CRM_DB_USER") or "crm_app"
    password = os.getenv("CRM_DB_PASSWORD") or "X17B3n5hbANQSRt6i7WIyy0lJudX"
    dbname = os.getenv("CRM_DB_DATABASE") or "crm"
    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=dbname)
    conn.autocommit = True
    return conn

class _SimpleDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, query, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return [dict(r) for r in cur.fetchall()]
    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

import streamlit as st

@st.cache_data(ttl=30)
def _load_research_filter_index_impl(procurement_ids: tuple[int, ...], _crm_db: Any) -> Dict[int, dict]:
    unique_ids = list(procurement_ids)
    
    # 1. Fetch active categories
    cat_map: Dict[str, str] = {}
    real_crm_db = _crm_db
    crm_conn_closeable = None
    if not real_crm_db or not hasattr(real_crm_db, "execute_query"):
        try:
            raw_crm_conn = _get_crm_db_conn()
            real_crm_db = _SimpleDbWrapper(raw_crm_conn)
            crm_conn_closeable = real_crm_db
        except Exception as e:
            logger.error(f"Failed _get_crm_db_conn in index: {e}")
            
    if real_crm_db:
        try:
            cat_rows = real_crm_db.execute_query(
                "SELECT category_code, category_name FROM crm_product_categories WHERE is_active = True"
            )
            for r in (cat_rows or []):
                code = r.get("category_code") or r.get("code")
                name = r.get("category_name") or r.get("name")
                if code and name:
                    cat_map[code] = name
        except Exception as e:
            logger.error(f"Error loading crm_product_categories in index: {e}")

    # 2. Fetch queue status
    queue_map: Dict[int, dict] = {}
    doc_conn_closeable = None
    try:
        raw_doc_conn = _get_doc_db_conn()
        doc_conn_wrapper = _SimpleDbWrapper(raw_doc_conn)
        doc_conn_closeable = doc_conn_wrapper
        
        q_rows = doc_conn_wrapper.execute_query(
            """
            SELECT DISTINCT ON (procurement_id)
                   procurement_id, id as queue_id, status, research_generation_hash,
                   created_at, started_at, completed_at
            FROM document_processing_queue
            WHERE pipeline_generation = %s AND procurement_id = ANY(%s)
            ORDER BY procurement_id, id DESC
            """,
            (PIPELINE_GENERATION, unique_ids),
        )
        for r in (q_rows or []):
            queue_map[r["procurement_id"]] = dict(r)
    except Exception as e:
        logger.error(f"Error querying queue in index: {e}")
    finally:
        if doc_conn_closeable:
            doc_conn_closeable.close()

    # Build active generation map (pid -> gen_hash)
    gen_map: Dict[int, str] = {}
    for pid, q_info in queue_map.items():
        gh = q_info.get("research_generation_hash")
        if gh:
            gen_map[pid] = gh

    # 3. Fetch truth records without parsing full manifest
    truth_map: Dict[Tuple[int, str], dict] = {}
    if gen_map and real_crm_db:
        try:
            t_rows = real_crm_db.execute_query(
                """
                SELECT procurement_id, research_generation_hash, documents_total,
                       documents_terminal_supported, documents_failed_or_unknown,
                       has_target_evidence, truth_completeness, evidence_count,
                       COALESCE(json_array_length(useful_documents_json), 0) as useful_cnt,
                       COALESCE(json_array_length(non_useful_documents_json), 0) as non_useful_cnt,
                       COALESCE(json_array_length(unknown_documents_json), 0) as unknown_cnt,
                       created_at
                FROM crm_v3_exhaustive_truth
                WHERE producer_version = 'v3_real_truth' AND procurement_id = ANY(%s)
                """,
                (unique_ids,),
            )
            for r in (t_rows or []):
                pid = r["procurement_id"]
                gh = r["research_generation_hash"]
                if gen_map.get(pid) == gh:
                    truth_map[(pid, gh)] = dict(r)
        except Exception as e:
            logger.error(f"Error querying crm_v3_exhaustive_truth in index: {e}")

    # 4. Fetch category codes aggregated in database
    evidence_codes_map: Dict[Tuple[int, str], List[str]] = {}
    if gen_map and real_crm_db:
        try:
            e_rows = real_crm_db.execute_query(
                """
                SELECT procurement_id, research_generation_hash, 
                       array_agg(DISTINCT suggested_category_code) as codes
                FROM crm_v3_raw_source_evidence
                WHERE pipeline_generation = %s AND procurement_id = ANY(%s)
                GROUP BY procurement_id, research_generation_hash
                """,
                (PIPELINE_GENERATION, unique_ids),
            )
            for r in (e_rows or []):
                pid = r["procurement_id"]
                gh = r["research_generation_hash"]
                if gen_map.get(pid) == gh:
                    codes = r.get("codes") or []
                    codes = [c for c in codes if c]
                    evidence_codes_map[(pid, gh)] = codes
        except Exception as e:
            logger.error(f"Error querying crm_v3_raw_source_evidence in index: {e}")

    if crm_conn_closeable:
        crm_conn_closeable.close()

    # Build simple dicts
    result = {}
    for pid in unique_ids:
        q_info = queue_map.get(pid)
        gh = q_info.get("research_generation_hash") if q_info else None
        
        r_state = "WAITING_RESEARCH"
        docs_total = 0
        docs_with_evidence = 0
        docs_no_evidence = 0
        docs_unknown = 0
        docs_researched = 0
        evidence_count = 0
        cat_codes = []
        
        if q_info:
            q_status = str(q_info.get("status") or "").upper()
            started_at = str(q_info.get("started_at") or q_info.get("created_at") or "")
            completed_at = str(q_info.get("completed_at") or "")
            
            truth_row = truth_map.get((pid, gh)) if gh else None
            ev_codes = evidence_codes_map.get((pid, gh)) if gh else None
            if ev_codes:
                cat_codes = ev_codes
                
            if truth_row:
                docs_total = truth_row.get("documents_total") or 0
                evidence_count = truth_row.get("evidence_count") or 0
                docs_with_evidence = truth_row.get("useful_cnt") or 0
                docs_no_evidence = truth_row.get("non_useful_cnt") or 0
                docs_unknown = truth_row.get("unknown_cnt") or 0
                docs_researched = docs_with_evidence + docs_no_evidence
                truth_comp = truth_row.get("truth_completeness")
                
                if evidence_count > 0 or docs_with_evidence > 0:
                    r_state = "EVIDENCE_FOUND"
                elif truth_comp == "COMPLETE" and docs_unknown == 0:
                    r_state = "NO_EVIDENCE"
                else:
                    r_state = "PARTIAL"
            else:
                evidence_count = len(cat_codes)
                if q_status in ("PENDING", "CLAIMED", "PROCESSING", "DOWNLOADING", "PARSING"):
                    r_state = "RESEARCHING"
                    if evidence_count > 0:
                        r_state = "EVIDENCE_FOUND"
                elif q_status in ("FAILED", "ERROR"):
                    r_state = "FAILED"
                elif q_status in ("COMPLETED", "NO_LINKS"):
                    if evidence_count > 0:
                        r_state = "EVIDENCE_FOUND"
                    else:
                        r_state = "NO_EVIDENCE"
                else:
                    r_state = "WAITING_RESEARCH"
        else:
            started_at = ""
            completed_at = ""

        cat_names = [cat_map.get(c, c) for c in cat_codes]
        
        result[pid] = {
            "procurement_id": pid,
            "research_generation_hash": gh,
            "research_state": r_state,
            "documents_total": docs_total,
            "documents_researched": docs_researched,
            "documents_remaining": max(0, docs_total - docs_researched),
            "documents_with_evidence": docs_with_evidence,
            "documents_no_evidence": docs_no_evidence,
            "documents_unknown": docs_unknown,
            "evidence_count": evidence_count,
            "category_codes": cat_codes,
            "category_names": cat_names,
            "started_at": started_at,
            "completed_at": completed_at,
        }
    return result

def load_research_filter_index(
    procurement_ids: List[int],
    crm_db: Any,
) -> Dict[int, ResearchUiProjection]:
    """Bulk load lightweight research UI projections for filtering.
    
    Loads only status/category information, completely avoiding manifest JSON
    and raw text database serialization.
    """
    if not procurement_ids:
        return {}
        
    unique_ids = tuple(sorted(list(set(procurement_ids))))
    raw_dicts = _load_research_filter_index_impl(unique_ids, crm_db)
    
    projections = {}
    for pid, d in raw_dicts.items():
        proj = ResearchUiProjection(procurement_id=pid)
        for k, v in d.items():
            setattr(proj, k, v)
        projections[pid] = proj
    return projections

def load_research_ui_projection(
    procurement_ids: List[int],
    crm_db: Any,
    *,
    _doc_db: Optional[Any] = None,
    _crm_db: Optional[Any] = None,
) -> Dict[int, ResearchUiProjection]:
    """Bulk load research UI projections for a list of procurement IDs.
    
    Executes max 6 bulk roundtrips per page (0 N+1 queries).
    Strictly queries document_intelligence DB for document queue identity.
    Production API accepts ONLY (procurement_ids, crm_db) - never UI-supplied doc_db wrappers.
    Strictly generation-scoped (CROSS_GENERATION_UI_EVIDENCE = 0).
    """
    if not procurement_ids:
        return {}

    unique_ids = list(set(procurement_ids))
    projections: Dict[int, ResearchUiProjection] = {
        pid: ResearchUiProjection(procurement_id=pid) for pid in unique_ids
    }

    # Open canonical CRM DB connection (or test wrapper)
    crm_conn_closeable = None
    if _crm_db and hasattr(_crm_db, "execute_query"):
        real_crm_db = _crm_db
    else:
        try:
            raw_crm_conn = _get_crm_db_conn()
            real_crm_db = _SimpleDbWrapper(raw_crm_conn)
            crm_conn_closeable = real_crm_db
        except Exception as conn_err:
            logger.error(f"Failed _get_crm_db_conn: {conn_err}")
            print(f"CRITICAL: Failed _get_crm_db_conn: {conn_err}")
            real_crm_db = crm_db

    # 1. Fetch active category names from crm_product_categories (CRM DB Roundtrip 1)
    cat_map: Dict[str, str] = {}
    try:
        cat_rows = real_crm_db.execute_query(
            "SELECT category_code, category_name FROM crm_product_categories WHERE is_active = True"
        )
        for r in (cat_rows or []):
            code = r.get("category_code") or r.get("code")
            name = r.get("category_name") or r.get("name")
            if code and name:
                cat_map[code] = name
    except Exception as e:
        logger.error(f"Error loading crm_product_categories: {e}")

    # 2. Open real document_intelligence connection ALWAYS (never accept UI source DB wrappers)
    doc_conn_closeable = None
    try:
        if _doc_db and hasattr(_doc_db, "execute_query"):
            doc_conn_wrapper = _doc_db
        else:
            raw_doc_conn = _get_doc_db_conn()
            doc_conn_wrapper = _SimpleDbWrapper(raw_doc_conn)
            doc_conn_closeable = doc_conn_wrapper
    except Exception as e:
        logger.error(f"CRITICAL: Failed to connect to document_intelligence database: {e}")
        for p in projections.values():
            p.research_state = "PROJECTION_ERROR"
            p.error_detail = f"DB_AUTHORITY_FAILURE: {e}"
        if crm_conn_closeable:
            crm_conn_closeable.close()
        return projections

    # 3. Fetch latest queue status & research_generation_hash per procurement (document_intelligence DB Roundtrip 1)
    queue_map: Dict[int, Dict[str, Any]] = {}
    try:
        q_rows = doc_conn_wrapper.execute_query(
            """
            SELECT DISTINCT ON (procurement_id)
                   procurement_id, id as queue_id, status, research_generation_hash,
                   created_at, started_at, completed_at
            FROM document_processing_queue
            WHERE pipeline_generation = %s AND procurement_id = ANY(%s)
            ORDER BY procurement_id, id DESC
            """,
            (PIPELINE_GENERATION, unique_ids),
        )
        for r in (q_rows or []):
            queue_map[r["procurement_id"]] = dict(r)
    except Exception as e:
        logger.error(f"Error querying document_processing_queue from document_intelligence DB: {e}")
        for p in projections.values():
            p.research_state = "PROJECTION_ERROR"
            p.error_detail = f"QUEUE_QUERY_FAILURE: {e}"
        if doc_conn_closeable:
            doc_conn_closeable.close()
        if crm_conn_closeable:
            crm_conn_closeable.close()
        return projections

    if doc_conn_closeable:
        doc_conn_closeable.close()

    # Build active generation map (pid -> gen_hash)
    gen_map: Dict[int, str] = {}
    for pid, q_info in queue_map.items():
        gh = q_info.get("research_generation_hash")
        if gh:
            gen_map[pid] = gh

    # 4. Fetch snapshots for active generations (CRM DB Roundtrip 2)
    snap_manifests: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    if gen_map:
        try:
            s_rows = real_crm_db.execute_query(
                """
                SELECT procurement_id, research_generation_hash, document_manifest_json
                FROM crm_v3_pre_research_snapshots
                WHERE producer_version = 'v3_real_truth' AND procurement_id = ANY(%s)
                """,
                (unique_ids,),
            )
            for r in (s_rows or []):
                pid = r["procurement_id"]
                gh = r["research_generation_hash"]
                if gen_map.get(pid) == gh:
                    man = r["document_manifest_json"]
                    if isinstance(man, str):
                        man = json.loads(man)
                    snap_manifests[(pid, gh)] = man or []
        except Exception as e:
            logger.error(f"Error querying crm_v3_pre_research_snapshots: {e}")

    # 5. Fetch exhaustive truth for active generations (CRM DB Roundtrip 3)
    truth_map: Dict[Tuple[int, str], Dict[str, Any]] = {}
    if gen_map:
        try:
            t_rows = real_crm_db.execute_query(
                """
                SELECT procurement_id, research_generation_hash, documents_total,
                       documents_terminal_supported, documents_failed_or_unknown,
                       has_target_evidence, useful_documents_json, non_useful_documents_json,
                       unknown_documents_json, evidence_count, truth_completeness, created_at
                FROM crm_v3_exhaustive_truth
                WHERE producer_version = 'v3_real_truth' AND procurement_id = ANY(%s)
                """,
                (unique_ids,),
            )
            for r in (t_rows or []):
                pid = r["procurement_id"]
                gh = r["research_generation_hash"]
                if gen_map.get(pid) == gh:
                    truth_map[(pid, gh)] = dict(r)
        except Exception as e:
            logger.error(f"Error querying crm_v3_exhaustive_truth: {e}")

    # 6. Fetch raw source evidence strictly for active generations (CRM DB Roundtrip 4)
    evidence_map: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    if gen_map:
        try:
            e_rows = real_crm_db.execute_query(
                """
                SELECT procurement_id, research_generation_hash, source_document_id,
                       document_name, matched_term, raw_text, context_before, context_after,
                       source_locator_json, suggested_category_code, created_at
                FROM crm_v3_raw_source_evidence
                WHERE pipeline_generation = %s AND procurement_id = ANY(%s)
                """,
                (PIPELINE_GENERATION, unique_ids),
            )
            for r in (e_rows or []):
                pid = r["procurement_id"]
                gh = r["research_generation_hash"]
                if gen_map.get(pid) == gh:
                    evidence_map.setdefault((pid, gh), []).append(dict(r))
        except Exception as e:
            logger.error(f"Error querying crm_v3_raw_source_evidence: {e}")

    if crm_conn_closeable:
        crm_conn_closeable.close()

    # Synthesize projections
    for pid, proj in projections.items():
        q_info = queue_map.get(pid)
        if not q_info:
            proj.research_state = "WAITING_RESEARCH"
            continue

        gh = q_info.get("research_generation_hash")
        proj.research_generation_hash = gh
        proj.started_at = str(q_info.get("started_at") or q_info.get("created_at") or "")
        proj.completed_at = str(q_info.get("completed_at") or "")
        q_status = str(q_info.get("status") or "").upper()

        manifest = snap_manifests.get((pid, gh), []) if gh else []
        proj.documents_total = len(manifest)

        ev_list = evidence_map.get((pid, gh), []) if gh else []
        proj.evidence_count = len(ev_list)

        cat_codes: Set[str] = set()
        matched_terms: Set[str] = set()
        for ev in ev_list:
            cc = ev.get("suggested_category_code")
            if cc:
                cat_codes.add(cc)
            mt = ev.get("matched_term")
            if mt:
                matched_terms.add(mt)

        proj.category_codes = sorted(list(cat_codes))
        proj.category_names = [cat_map.get(c, c) for c in proj.category_codes]
        proj.top_matched_terms = sorted(list(matched_terms))[:10]

        truth_row = truth_map.get((pid, gh)) if gh else None

        if truth_row:
            proj.truth_completeness = truth_row.get("truth_completeness")
            proj.documents_total = truth_row.get("documents_total") or len(manifest)

            useful_docs = truth_row.get("useful_documents_json") or []
            if isinstance(useful_docs, str):
                useful_docs = json.loads(useful_docs)

            non_useful_docs = truth_row.get("non_useful_documents_json") or []
            if isinstance(non_useful_docs, str):
                non_useful_docs = json.loads(non_useful_docs)

            unknown_docs = truth_row.get("unknown_documents_json") or []
            if isinstance(unknown_docs, str):
                unknown_docs = json.loads(unknown_docs)

            proj.documents_with_evidence = len(useful_docs)
            proj.documents_no_evidence = len(non_useful_docs)
            proj.documents_unknown = len(unknown_docs)
            proj.documents_researched = proj.documents_with_evidence + proj.documents_no_evidence

            if proj.evidence_count > 0 or proj.documents_with_evidence > 0:
                proj.research_state = "EVIDENCE_FOUND"
            elif proj.truth_completeness == "COMPLETE" and proj.documents_unknown == 0:
                proj.research_state = "NO_EVIDENCE"
            else:
                proj.research_state = "PARTIAL"
        else:
            if q_status in ("PENDING", "CLAIMED", "PROCESSING", "DOWNLOADING", "PARSING"):
                proj.research_state = "RESEARCHING"
                if proj.evidence_count > 0:
                    proj.research_state = "EVIDENCE_FOUND"
            elif q_status in ("FAILED", "ERROR"):
                proj.research_state = "FAILED"
            elif q_status in ("COMPLETED", "NO_LINKS"):
                if proj.evidence_count > 0:
                    proj.research_state = "EVIDENCE_FOUND"
                else:
                    proj.research_state = "NO_EVIDENCE"
            else:
                proj.research_state = "WAITING_RESEARCH"

    return projections

def filter_research_workset_ids(
    procurement_ids: List[int],
    projections: Dict[int, ResearchUiProjection],
    selected_research: str = "ALL",
    selected_category: str = "ALL",
) -> List[int]:
    """Filter workset procurement IDs by research state and found category BEFORE pagination.
    
    Preserves input ID ordering and identity.
    """
    if selected_research == "ALL" and selected_category == "ALL":
        return procurement_ids

    filtered: List[int] = []
    for pid in procurement_ids:
        proj = projections.get(pid)
        r_state = proj.research_state if proj else "WAITING_RESEARCH"

        if selected_research != "ALL" and r_state != selected_research:
            continue

        if selected_category != "ALL":
            c_names = proj.category_names if proj else []
            c_codes = proj.category_codes if proj else []
            if selected_category not in c_names and selected_category not in c_codes:
                continue

        filtered.append(pid)

    return filtered
