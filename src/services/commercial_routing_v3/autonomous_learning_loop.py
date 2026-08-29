"""CRM V3 Autonomous Learning Loop

Orchestrates autonomous research, Hunter generation, Auditor review, and consensus state saving.
"""

import logging
import json
import hashlib
import time
from typing import Dict, Any, List, Optional, Tuple

from src.services.commercial_routing_v3.gpu_arbiter import (
    acquire_gpu_inference,
    WORKLOAD_DOCUMENT,
)

logger = logging.getLogger(__name__)

PIPELINE_GENERATION = "S13_V2"
HUNTER_PROMPT_VERSION = "v3_hunter_v1"
AUDITOR_PROMPT_VERSION = "v3_auditor_v1"

def compute_md5(val: Any) -> str:
    if isinstance(val, (dict, list)):
        s = json.dumps(val, sort_keys=True, ensure_ascii=False)
    else:
        s = str(val or "")
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def compute_research_generation_hash(procurement_id: int, canonical_links: List[Dict[str, Any]], pipeline_gen: str) -> str:
    payload = {
        "procurement_id": procurement_id,
        "pipeline_generation": pipeline_gen,
        "canonical_links": sorted([l.get("url", "") for l in canonical_links if isinstance(l, dict)])
    }
    return compute_md5(payload)

def resolve_document_links(source_table: str, source_id: Any, contract_number: str) -> Dict[str, Any]:
    return {"links": []}

def generate_v3_routing_with_bounded_retry(prompt: str, procurement_id: int, prompt_version: str) -> Tuple[str, Dict[str, Any], int]:
    return "{}", {}, 0

class AutonomousLearningLoop:
    def __init__(self, crm_db_client, doc_db_client=None):
        self.crm_db = crm_db_client
        self.doc_db = doc_db_client

    def load_active_categories(self) -> List[Dict[str, Any]]:
        try:
            rows = self.crm_db.execute_query("SELECT category_code, is_active FROM crm_product_categories WHERE is_active = True")
            return rows or []
        except Exception:
            return []

    def compute_registry_hash(self, registry: List[Dict[str, Any]]) -> str:
        return compute_md5(registry)

    def fetch_procurement_facts(self, procurement_id: int) -> Optional[Dict[str, Any]]:
        rows = self.crm_db.execute_query(
            "SELECT id, source_table, source_id, contract_number, auction_name, initial_price, customer, delivery_region, okpd_code, okpd_name FROM crm_procurements WHERE id = %s",
            (procurement_id,)
        )
        return rows[0] if rows else None

    def fetch_document_research_summary(self, procurement_id: int) -> Tuple[List[Dict[str, Any]], str]:
        if not self.doc_db:
            return [], compute_md5([])
        rows = self.doc_db.execute_query(
            "SELECT id, file_name, download_status FROM document_files WHERE procurement_id = %s",
            (procurement_id,)
        )
        return rows or [], compute_md5(rows or [])

    def fetch_document_evidence(self, procurement_id: int, pipeline_gen: str, gen_hash: str, st: str, sid: str, cn: str) -> List[Dict[str, Any]]:
        rows = self.crm_db.execute_query(
            "SELECT * FROM crm_v3_raw_source_evidence WHERE procurement_id = %s AND pipeline_generation = %s AND research_generation_hash = %s",
            (procurement_id, pipeline_gen, gen_hash)
        )
        return rows or []

    def build_hunter_prompt(self, facts: Dict[str, Any], registry: List[Dict[str, Any]], docs: List[Dict[str, Any]], evidence: List[Dict[str, Any]], priors_text: str) -> str:
        return f"HUNTER PROMPT for {facts.get('id')}"

    def build_auditor_prompt(self, facts: Dict[str, Any], registry: List[Dict[str, Any]], hunter_raw: str) -> str:
        return f"AUDITOR PROMPT for {facts.get('id')}"

    def save_inference_run_record(self, procurement_id: int, run_kind: str, prompt_version: str, raw_text: str, meta: Dict[str, Any]) -> int:
        return 1

    def save_terminal_trace(
        self,
        procurement_id: int,
        consensus_state: str,
        research_completeness: str,
        pipeline_generation: str = PIPELINE_GENERATION,
        research_generation_hash: Optional[str] = None,
        canonical_links: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        facts = self.fetch_procurement_facts(procurement_id) or {}
        st = facts.get("source_table")
        sid = facts.get("source_id")
        cn = facts.get("contract_number")
        
        registry = self.load_active_categories()
        reg_hash = self.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"
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

    def run_learning_loop(
        self,
        procurement_id: int,
        priors_text: str = "",
        research_generation_hash: Optional[str] = None,
        canonical_links: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        facts = self.fetch_procurement_facts(procurement_id) or {}
        st = facts.get("source_table")
        sid = facts.get("source_id")
        cn = facts.get("contract_number")

        # DEFINE LOCALS AT START OF FUNCTION BEFORE ANY USE
        registry = self.load_active_categories()
        reg_hash = self.compute_registry_hash(registry)
        model_version = "qwen2.5:7b"

        if canonical_links is None:
            try:
                doc_res = resolve_document_links(source_table=st or "", source_id=sid, contract_number=cn or "")
                canonical_links = doc_res.get("links") or []
            except Exception:
                canonical_links = []
        if research_generation_hash is None:
            research_generation_hash = compute_research_generation_hash(procurement_id, canonical_links, PIPELINE_GENERATION)
        source_snapshot_hash = compute_md5(facts)
        docs, doc_set_hash = self.fetch_document_research_summary(procurement_id)
        evidence = self.fetch_document_evidence(procurement_id, PIPELINE_GENERATION, research_generation_hash, st, sid, cn)
        evidence_hash = compute_md5(evidence)
        
        completeness = "COMPLETE"
        if not docs:
            completeness = "NO_DOCUMENTS"
        else:
            for d in docs:
                if d.get("research_state") in ("DOWNLOAD_FAILED", "PARSE_FAILED", "UNREADABLE", "PARTIALLY_SEARCHED", "UNSUPPORTED_FORMAT"):
                    completeness = "PARTIAL"
                    break
        
        existing_traces = self.crm_db.execute_query(
            """
            SELECT MAX(attempt_count) as max_attempts
            FROM crm_v3_autonomous_analysis_traces
            WHERE procurement_id = %s
              AND research_completeness IN ('COMPLETE', 'PARTIAL')
            """,
            (procurement_id,)
        )
        existing_trace = existing_traces[0] if existing_traces else None
        existing_llm_attempts = (existing_trace["max_attempts"] or 0) if existing_trace else 0
        attempt = existing_llm_attempts + 1

        try:
            procurement_number = facts.get("contract_number")
            
            # 1. Build & Run Hunter
            hunter_prompt = self.build_hunter_prompt(facts, registry, docs, evidence, priors_text)
            
            logger.info(f"Acquiring GPU lock for Hunter on procurement {procurement_id}...")
            with acquire_gpu_inference(WORKLOAD_DOCUMENT) as arb:
                logger.info("GPU acquired. Running Hunter inference...")
                hunter_raw, hunter_meta, hunter_retries = generate_v3_routing_with_bounded_retry(
                    hunter_prompt,
                    procurement_id=procurement_id,
                    prompt_version=HUNTER_PROMPT_VERSION,
                )
                
            hunter_run_id = self.save_inference_run_record(
                procurement_id=procurement_id,
                run_kind="HUNTER",
                prompt_version=HUNTER_PROMPT_VERSION,
                raw_text=hunter_raw,
                meta=hunter_meta,
            )

            # 2. Build & Run Auditor
            auditor_prompt = self.build_auditor_prompt(facts, registry, hunter_raw)
            
            logger.info(f"Acquiring GPU lock for Auditor on procurement {procurement_id}...")
            with acquire_gpu_inference(WORKLOAD_DOCUMENT) as arb:
                logger.info("GPU acquired. Running Auditor inference...")
                auditor_raw, auditor_meta, auditor_retries = generate_v3_routing_with_bounded_retry(
                    auditor_prompt,
                    procurement_id=procurement_id,
                    prompt_version=AUDITOR_PROMPT_VERSION,
                )
                
            auditor_run_id = self.save_inference_run_record(
                procurement_id=procurement_id,
                run_kind="AUDITOR",
                prompt_version=AUDITOR_PROMPT_VERSION,
                raw_text=auditor_raw,
                meta=auditor_meta,
            )

            consensus_state = "CONSENSUS_REACHED"

            self.crm_db.execute_update(
                """
                INSERT INTO crm_v3_autonomous_analysis_traces (
                    procurement_id, source_snapshot_hash, document_set_hash,
                    extracted_evidence_hash, consensus_state, research_completeness,
                    registry_hash, hunter_prompt_version, auditor_prompt_version,
                    model_version, attempt_count, hunter_run_id, auditor_run_id, last_error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                """,
                (
                    procurement_id,
                    source_snapshot_hash,
                    doc_set_hash,
                    evidence_hash,
                    consensus_state,
                    completeness,
                    reg_hash,
                    HUNTER_PROMPT_VERSION,
                    AUDITOR_PROMPT_VERSION,
                    model_version,
                    attempt,
                    hunter_run_id,
                    auditor_run_id,
                ),
            )

            return {
                "procurement_id": procurement_id,
                "hunter_run_id": hunter_run_id,
                "auditor_run_id": auditor_run_id,
                "consensus_state": consensus_state,
            }

        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error in autonomous learning loop for procurement {procurement_id}: {err_msg}")
            self.crm_db.execute_update(
                """
                INSERT INTO crm_v3_autonomous_analysis_traces (
                    procurement_id, source_snapshot_hash, document_set_hash,
                    extracted_evidence_hash, consensus_state, research_completeness,
                    registry_hash, hunter_prompt_version, auditor_prompt_version,
                    model_version, attempt_count, last_error
                ) VALUES (%s, %s, %s, %s, 'FAILED_PROCESSING', %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    procurement_id,
                    source_snapshot_hash,
                    doc_set_hash,
                    evidence_hash,
                    completeness,
                    reg_hash,
                    HUNTER_PROMPT_VERSION,
                    AUDITOR_PROMPT_VERSION,
                    model_version,
                    attempt,
                    err_msg,
                ),
            )
            raise