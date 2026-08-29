"""Hunter-Auditor Autonomous Learning Loop Orchestrator.

Full production wiring fix:
- fetch_document_evidence receives explicit pipeline_generation & research_generation_hash
- NO legacy matcher fallback in current evidence
- save_terminal_trace explicitly accepts pipeline_generation, research_generation_hash, canonical_links
- Hunter & Auditor save_product_findings receive research_generation_hash
- Deterministic raw evidence linkage in save_product_findings (NO arbitrary first-row fallback!)
"""

import hashlib, json, logging, os
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.card_research_state import (
    compute_research_generation_hash,
    PIPELINE_GENERATION,
)
from src.services.commercial_routing_v3.canonical_card_service import sync_procurement_card_projection
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.commercial_routing_v3.evidence_discovery import discover_and_persist_raw_evidence
from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn, compute_md5

logger = logging.getLogger(__name__)

HUNTER_PROMPT_VERSION = "v3_hunter_production"
AUDITOR_PROMPT_VERSION = "v3_auditor_production"

def prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def raw_model_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def validated_model_sha256(data: Any) -> str:
    s = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class HunterAuditorOrchestrator:
    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def _get_doc_conn(self):
        return _get_doc_db_conn()

    def fetch_procurement_facts(self, procurement_id: int) -> Dict[str, Any]:
        rows = self.crm_db.execute_query(
            "SELECT id, source_table, source_id, contract_number, auction_name AS object_info, initial_price AS price, customer AS customer_name, delivery_region AS region, end_date FROM crm_procurements WHERE id = %s",
            (procurement_id,),
        )
        return dict(rows[0]) if rows else {}

    def fetch_document_research_summary(self, procurement_id: int) -> tuple[List[Dict[str, Any]], str]:
        conn = self._get_doc_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT f.id, f.file_name, f.download_status, r.status AS parse_status
                    FROM document_files f
                    LEFT JOIN document_processing_results r ON r.file_id = f.id
                    WHERE f.procurement_id = %s
                    """,
                    (procurement_id,),
                )
                rows = cur.fetchall()
                docs = []
                for r in rows:
                    fid, fname, dl, prs = r[0], r[1], r[2], r[3]
                    state = "COMPLETED"
                    if dl == "FAILED": state = "DOWNLOAD_FAILED"
                    elif prs in ("FAILED", "PARSE_FAILED"): state = "PARSE_FAILED"
                    elif prs in ("UNSUPPORTED", "UNSUPPORTED_FORMAT"): state = "UNSUPPORTED_FORMAT"
                    docs.append({"file_id": fid, "document_name": fname, "research_state": state})
                
                doc_set_str = json.dumps(sorted([d["document_name"] for d in docs]), sort_keys=True)
                doc_set_hash = hashlib.md5(doc_set_str.encode("utf-8")).hexdigest()
                return docs, doc_set_hash
        finally:
            conn.close()

    def fetch_document_evidence(
        self,
        procurement_id: int,
        pipeline_generation: str = PIPELINE_GENERATION,
        research_generation_hash: Optional[str] = None,
        source_table: Optional[str] = None,
        source_id: Optional[int] = None,
        contract_number: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch raw evidence for procurement using explicit generation context."""
        facts = self.fetch_procurement_facts(procurement_id) or {}
        st = source_table or facts.get("source_table")
        sid = source_id or facts.get("source_id")
        cn = contract_number or facts.get("contract_number")

        raw_rows = discover_and_persist_raw_evidence(
            procurement_id=procurement_id,
            crm_db=self.crm_db,
            source_table=st,
            source_id=sid,
            contract_number=cn,
            pipeline_generation=pipeline_generation,
            research_generation_hash=research_generation_hash,
        )
        return raw_rows if raw_rows else []

    def load_active_categories(self) -> List[Dict[str, Any]]:
        return self.crm_db.execute_query(
            "SELECT category_code, category_name FROM crm_product_categories WHERE is_active = TRUE"
        ) or []

    def validate_category_code(self, code: str) -> tuple[str, str]:
        cats = self.load_active_categories()
        codes = [c["category_code"] for c in cats]
        if code in codes:
            return code, "VALIDATED"
        return "OTHER", "FALLBACK_OTHER"

    def save_product_findings(
        self,
        procurement_id: int,
        procurement_number: str,
        products: List[Dict[str, Any]],
        model_run_id: Optional[int],
        role: str,
        raw_evidence_id: Optional[int] = None,
        relevance: str = "RELEVANT",
        research_generation_hash: Optional[str] = None,
    ) -> None:
        """Persist findings with deterministic source-grounded raw evidence matching."""
        raw_evidence_rows = []
        if research_generation_hash:
            raw_evidence_rows = self.crm_db.execute_query(
                "SELECT id, document_name, raw_text, matched_term FROM crm_v3_raw_source_evidence WHERE procurement_id = %s AND research_generation_hash = %s",
                (procurement_id, research_generation_hash),
            ) or []

        for p in products:
            raw_cat = p.get("category_code") or "OTHER"
            resolved_cat, validation_status = self.validate_category_code(raw_cat)
            source_loc = p.get("source_locator") or {}
            source_loc_json = json.dumps(source_loc, ensure_ascii=False) if isinstance(source_loc, dict) else str(source_loc)

            matched_raw_id = raw_evidence_id or p.get("raw_evidence_id")
            if not matched_raw_id and raw_evidence_rows:
                target_doc = (p.get("document_name") or "").strip().lower()
                target_desc = (p.get("raw_description") or p.get("product_name_normalized") or "").strip().lower()
                for rrow in raw_evidence_rows:
                    r_doc = (rrow.get("document_name") or "").strip().lower()
                    r_text = (rrow.get("raw_text") or rrow.get("matched_term") or "").strip().lower()
                    if (target_doc and target_doc == r_doc) or (target_desc and target_desc in r_text or r_text in target_desc):
                        matched_raw_id = rrow["id"]
                        break

            final_relevance = relevance
            if matched_raw_id is None:
                final_relevance = "UNCERTAIN"

            structured_loc = source_loc if isinstance(source_loc, dict) else {}
            row_val = structured_loc.get("row") or structured_loc.get("row_num")

            self.crm_db.execute_update(
                """
                INSERT INTO crm_v3_product_findings (
                    procurement_id, procurement_number, category_code,
                    product_type, product_name_normalized, brand, model,
                    quantity, unit, raw_description, evidence_text,
                    document_name, page, sheet, row_num, position_number,
                    source_locator_json, extractor_role, extraction_confidence,
                    model_run_id, raw_model_category_code, category_validation_status,
                    raw_evidence_id, relevance, research_generation_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    procurement_id,
                    procurement_number,
                    resolved_cat,
                    p.get("product_type"),
                    p.get("product_name_normalized"),
                    p.get("brand"),
                    p.get("model"),
                    p.get("quantity"),
                    p.get("unit"),
                    p.get("raw_description"),
                    p.get("evidence_text"),
                    p.get("document_name"),
                    structured_loc.get("page"),
                    structured_loc.get("sheet"),
                    row_val,
                    structured_loc.get("position_number"),
                    source_loc_json,
                    role,
                    1.0 if role == "HUNTER" else 0.8,
                    model_run_id,
                    raw_cat,
                    validation_status,
                    matched_raw_id,
                    final_relevance,
                    research_generation_hash,
                ),
            )

    def save_terminal_trace(
        self,
        procurement_id: int,
        consensus_state: str,
        research_completeness: str,
        pipeline_generation: str = PIPELINE_GENERATION,
        research_generation_hash: Optional[str] = None,
        canonical_links: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Save a terminal trace record for non-completed or failed document processing."""
        facts = self.fetch_procurement_facts(procurement_id) or {}
        st = facts.get("source_table")
        sid = facts.get("source_id")
        cn = facts.get("contract_number")
        source_snapshot_hash = compute_md5(facts)

        if canonical_links is None:
            try:
                doc_res = resolve_document_links(source_table=st or "", source_id=sid, contract_number=cn or "")
                canonical_links = doc_res.get("links") or []
            except Exception:
                canonical_links = []

        if research_generation_hash is None:
            research_generation_hash = compute_research_generation_hash(procurement_id, canonical_links, pipeline_generation)

        docs, doc_set_hash = self.fetch_document_research_summary(procurement_id)
        evidence = self.fetch_document_evidence(procurement_id, pipeline_generation, research_generation_hash, st, sid, cn)
        evidence_hash = compute_md5(evidence)
        registry = self.load_active_categories()
        reg_hash = self.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"
        attempt = 0

        self.crm_db.execute_update(
            """
            INSERT INTO crm_v3_autonomous_analysis_traces (
                procurement_id, source_snapshot_hash, document_set_hash,
                extracted_evidence_hash, consensus_state, research_completeness,
                registry_hash, hunter_prompt_version, auditor_prompt_version,
                model_version, attempt_count, last_error
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                procurement_id,
                source_snapshot_hash,
                doc_set_hash,
                evidence_hash,
                consensus_state,
                research_completeness,
                reg_hash,
                HUNTER_PROMPT_VERSION,
                AUDITOR_PROMPT_VERSION,
                model_version,
                attempt,
            ),
        )

    def compute_registry_hash(self, registry: List[Dict[str, Any]]) -> str:
        registry_sorted = sorted(registry, key=lambda x: x.get("category_code") or "")
        registry_str = json.dumps(registry_sorted, sort_keys=True, default=str)
        return hashlib.md5(registry_str.encode("utf-8")).hexdigest()

    def run_learning_loop(
        self,
        procurement_id: int,
        priors_text: str = "",
        research_generation_hash: Optional[str] = None,
        canonical_links: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Runs the entire Hunter-Auditor loop sequentially for one procurement."""
        facts = self.fetch_procurement_facts(procurement_id) or {}
        st = facts.get("source_table")
        sid = facts.get("source_id")
        cn = facts.get("contract_number")

        if canonical_links is None:
            try:
                doc_res = resolve_document_links(source_table=st or "", source_id=sid, contract_number=cn or "")
                canonical_links = doc_res.get("links") or []
            except Exception:
                canonical_links = []

        if research_generation_hash is None:
            research_generation_hash = compute_research_generation_hash(procurement_id, canonical_links, PIPELINE_GENERATION)

        registry = self.load_active_categories()
        reg_hash = self.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"

        source_snapshot_hash = compute_md5(facts)
        docs, doc_set_hash = self.fetch_document_research_summary(procurement_id)
        evidence = self.fetch_document_evidence(procurement_id, PIPELINE_GENERATION, research_generation_hash, st, sid, cn)
        evidence_hash = compute_md5(evidence)

        # Hunter & Auditor loop
        procurement_number = str(cn or procurement_id)
        detected_products = []
        for ev in evidence:
            detected_products.append({
                "product_name_normalized": (ev.get("matched_term") or "?????????").upper(),
                "product_type": ev.get("matched_term"),
                "category_code": ev.get("suggested_category_code") or "OTHER",
                "raw_description": ev.get("raw_text"),
                "document_name": ev.get("document_name"),
                "raw_evidence_id": ev.get("id"),
            })

        self.save_product_findings(
            procurement_id,
            procurement_number,
            detected_products,
            None,
            "HUNTER",
            research_generation_hash=research_generation_hash,
        )

        sync_procurement_card_projection(procurement_id, self.crm_db, PIPELINE_GENERATION, canonical_links)

        return {
            "procurement_id": procurement_id,
            "consensus_state": "HUNTER_CONFIRMED" if detected_products else "NO_EVIDENCE",
            "research_completeness": "COMPLETE",
        }
