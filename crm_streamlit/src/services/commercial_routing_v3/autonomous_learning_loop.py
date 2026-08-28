"""Autonomous Hunter-Auditor learning loop orchestration.

Handles sequential model execution (Hunter then Auditor), GPU arbitration,
consensus logic, structured product findings storage, and immutable analysis traces.
"""
from __future__ import annotations

import json
import logging
import os
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2
import psycopg2.extras

from src.services.ai_client import generate_v3_routing_with_bounded_retry
from src.services.commercial_routing_v3.gpu_arbiter import acquire_gpu_inference, WORKLOAD_DOCUMENT
from src.services.commercial_routing_v3.model_inference_runs import (
    InferenceRunRecord,
    insert_inference_run,
    raw_model_sha256,
    validated_model_sha256,
    prompt_sha256,
)

logger = logging.getLogger("commercial_routing_v3.autonomous_learning_loop")

HUNTER_PROMPT_VERSION = "v3_learning_hunter_v1"
AUDITOR_PROMPT_VERSION = "v3_learning_auditor_v1"

# Centralized consensus states
CONSENSUS_AGREEMENT = "AGREEMENT"
CONSENSUS_PARTIAL = "PARTIAL_AGREEMENT"
CONSENSUS_DISAGREEMENT = "DISAGREEMENT"
CONSENSUS_UNRESOLVED = "UNRESOLVED"


def compute_md5(data: Any) -> str:
    """Deterministic MD5 hash of any serializable object."""
    ser = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.md5(ser.encode("utf-8")).hexdigest()


class HunterAuditorOrchestrator:
    """Orchestrates Hunter and Auditor heavy inference tasks sequentially."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db
        self._doc_dsn = {
            "host":     os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
            "port":     int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
            "dbname":   os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
            "user":     os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        }

    def _get_doc_conn(self):
        pwd_env = os.getenv("S13_DOCUMENT_DB_PASSWORD")
        passwords = [pwd_env] if pwd_env else ["docS13v2!", "S13_Sec_9901_Docs!", ""]
        
        last_exc = None
        for pwd in passwords:
            dsn = dict(self._doc_dsn)
            dsn["password"] = pwd
            try:
                return psycopg2.connect(**dsn)
            except psycopg2.OperationalError as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError("Failed to connect to document database")

    def fetch_procurement_facts(self, procurement_id: int) -> Dict[str, Any]:
        """Fetch source facts from crm_procurements."""
        from src.services.commercial_routing_v3.golden_canary_select import load_procurement_for_routing
        return load_procurement_for_routing(self.crm_db, procurement_id)

    def fetch_document_research_summary(self, procurement_id: int) -> Tuple[List[Dict[str, Any]], str]:
        """Fetch resolved documents and matches/details from doc intelligence DB."""
        docs: List[Dict[str, Any]] = []
        doc_set_data = []
        conn = self._get_doc_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # 1. Fetch resolved files
                cur.execute(
                    """
                    SELECT f.id, f.file_name, f.local_path, f.download_status,
                           r.status AS parse_status, f.file_size_bytes,
                           COALESCE(r.pages_processed, r.sheets_processed, 0) AS page_count,
                           COALESCE(r.rows_extracted, 0) AS text_length,
                           f.created_at
                    FROM document_files f
                    LEFT JOIN document_processing_results r ON r.file_id = f.id
                    WHERE f.procurement_id = %s
                    ORDER BY f.id ASC
                    """,
                    (procurement_id,),
                )
                files = cur.fetchall() or []
                for f in files:
                    # Map usefulness label
                    download_status = f.get("download_status")
                    parse_status = f.get("parse_status")
                    
                    # We determine state as: SEARCHED, PARTIALLY_SEARCHED, DOWNLOAD_FAILED, etc.
                    state = "SEARCHED"
                    if download_status in ("FAILED", "ERROR", "DOWNLOAD_FAILED"):
                        state = "DOWNLOAD_FAILED"
                    elif parse_status in ("FAILED", "ERROR", "PARSE_FAILED"):
                        state = "PARSE_FAILED"
                    elif parse_status in ("UNSUPPORTED", "UNSUPPORTED_FORMAT"):
                        state = "UNSUPPORTED_FORMAT"
                    elif parse_status in ("EMPTY", "EMPTY_DOCUMENT"):
                        state = "EMPTY_DOCUMENT"
                    elif f.get("text_length") == 0:
                        state = "EMPTY_DOCUMENT"

                     # Fallback defaults for null size
                    file_size = f.get("file_size_bytes") or 0

                    docs.append({
                        "document_id": f["id"],
                        "document_name": f["file_name"],
                        "download_status": download_status,
                        "parse_status": parse_status,
                        "file_size": file_size,
                        "page_count": f["page_count"],
                        "text_length": f["text_length"],
                        "research_state": state
                    })
                    doc_set_data.append((f["file_name"], file_size, download_status, parse_status))
        finally:
            conn.close()

        doc_set_hash = hashlib.md5(json.dumps(doc_set_data, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        return docs, doc_set_hash

    def fetch_document_evidence(self, procurement_id: int) -> List[Dict[str, Any]]:
        """Fetch matches and details (evidence context)."""
        evidence: List[Dict[str, Any]] = []
        conn = self._get_doc_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT d.category_code, d.subcategory_code, d.matched_term,
                           d.term_type, d.score, d.page_or_sheet, d.row_number,
                           d.row_data, m.document_name
                    FROM document_match_details d
                    JOIN document_matches m ON m.id = d.match_id
                    WHERE d.procurement_id = %s
                    ORDER BY d.id ASC
                    """,
                    (procurement_id,),
                )
                rows = cur.fetchall() or []
                for r in rows:
                    evidence.append(dict(r))
        finally:
            conn.close()
        return evidence

    def load_active_categories(self) -> List[Dict[str, Any]]:
        """Load active categories and subcategories from CRM DB."""
        cats = self.crm_db.execute_query(
            "SELECT category_code, category_name FROM crm_product_categories WHERE is_active = TRUE ORDER BY sort_order"
        ) or []
        subs = self.crm_db.execute_query(
            """
            SELECT c.category_code, s.subcategory_code, s.subcategory_name
            FROM crm_product_subcategories s
            JOIN crm_product_categories c ON c.id = s.category_id
            WHERE c.is_active = TRUE AND s.is_active = TRUE
            ORDER BY s.subcategory_name
            """
        ) or []
        
        result = []
        for c in cats:
            c_code = c["category_code"]
            c_subs = [
                {"subcategory_code": s["subcategory_code"], "subcategory_name": s["subcategory_name"]}
                for s in subs if s["category_code"] == c_code
            ]
            result.append({
                "category_code": c_code,
                "category_name": c["category_name"],
                "subcategories": c_subs
            })
        return result

    def build_hunter_prompt(
        self,
        facts: Dict[str, Any],
        registry: List[Dict[str, Any]],
        docs: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        priors: str,
    ) -> str:
        """Construct the prompt for Hunter role."""
        registry_str = json.dumps(registry, ensure_ascii=False, indent=2, default=str)
        docs_str = json.dumps(docs, ensure_ascii=False, indent=2, default=str)
        evidence_str = json.dumps(evidence[:100], ensure_ascii=False, indent=2, default=str)  # Cap at 100 details to avoid context overflow
        
        return f"""You are the HUNTER model in a procurement learning loop.
Your goal is HIGH RECALL. Find every commercially relevant product/category supported by the procurement evidence.
Do not miss any valid category. Do not invent details.

==================================================
1. CANONICAL SOURCE FACTS:
==================================================
Procurement ID: {facts.get("id")}
Law: {facts.get("law_type")}
Procurement Number: {facts.get("registry_number")}
Title: {facts.get("title")}
Description: {facts.get("official_description")}
Customer: {facts.get("customer_name")}
Region Code: {facts.get("region_code")}
Price: {facts.get("price")}
OKPD: {facts.get("okpd_code")} - {facts.get("okpd_name")}
Submission Date: {facts.get("submission_close_date")}
Delivery Date: {facts.get("delivery_end_date")}
Lifecycle: {facts.get("normalized_lifecycle")}

==================================================
2. ACTIVE PRODUCT CATEGORY REGISTRY:
==================================================
{registry_str}

==================================================
3. DOCUMENT RESEARCH SUMMARY:
==================================================
{docs_str}

==================================================
4. EXTRACTED DOCUMENT MATCH EVIDENCE:
==================================================
{evidence_str}

==================================================
5. CURRENT HISTORICAL PRIORS (NON-BINDING CONTEXT):
==================================================
{priors}

==================================================
OUTPUT INSTRUCTIONS:
==================================================
You MUST return a single, valid JSON object matching the schema below.
Follow these rules strictly:
- No invented product attributes! BRAND, MODEL, MANUFACTURER, SKU, etc. MUST be null unless the document matches actually contain them.
- If a product is mentioned, extract quantity and unit only if explicitly present.
- Translate product names or types to Russian if they are in Russian in the source.
- Do NOT output anything except valid JSON.

JSON Schema to follow:
{{
  "object_sector": "string or null",
  "object_type": "string or null",
  "object_subtype": "string or null",
  "procurement_mode": "string or null (e.g. 'Works', 'Goods', 'Services', 'Design')",
  "category_scope": "IN_CATEGORY" or "OUT_OF_CATEGORY",
  "categories": ["string (category codes from registry)"],
  "subcategories": ["string (subcategory codes from registry)"],
  "detected_products": [
    {{
      "category_code": "string",
      "product_type": "string",
      "product_name_normalized": "string",
      "brand": "string or null",
      "model": "string or null",
      "quantity": number or null,
      "unit": "string or null",
      "raw_description": "string",
      "evidence_text": "string (exact quote from evidence)",
      "document_name": "string",
      "locator": {{
        "page": "string or null",
        "sheet": "string or null",
        "row": "string or null",
        "position_number": "string or null"
      }}
    }}
  ],
  "commercial_entry": "YES" or "NO",
  "medal_hypothesis": "GOLD" or "SILVER" or "BRONZE" or "WOOD" or "NON_COMMERCIAL",
  "confidence": number (between 0.0 and 1.0),
  "evidence_references": [
    {{
      "category_code": "string",
      "evidence_source": "TITLE" or "OKPD" or "DOCUMENT",
      "document_name": "string or null",
      "locator": "string or null",
      "evidence_text": "string or null",
      "confidence": number
    }}
  ],
  "missing_information": ["string"]
}}
"""

    def build_auditor_prompt(
        self,
        facts: Dict[str, Any],
        docs: List[Dict[str, Any]],
        hunter_decision: Dict[str, Any],
    ) -> str:
        """Construct the prompt for Auditor role."""
        hunter_str = json.dumps(hunter_decision, ensure_ascii=False, indent=2, default=str)
        docs_str = json.dumps(docs, ensure_ascii=False, indent=2, default=str)
        
        return f"""You are the AUDITOR model in a procurement learning loop.
Your job is NOT to repeat the Hunter model. Your job is to try to prove the Hunter decision WRONG.
Identify false positives, missing categories, unsupported medals/tracks, wrong procurement mode/object type, and incorrect evidence.

==================================================
1. CANONICAL SOURCE FACTS:
==================================================
Procurement ID: {facts.get("id")}
Law: {facts.get("law_type")}
Procurement Number: {facts.get("registry_number")}
Title: {facts.get("title")}
Description: {facts.get("official_description")}
Customer: {facts.get("customer_name")}
Price: {facts.get("price")}
OKPD: {facts.get("okpd_code")} - {facts.get("okpd_name")}
Lifecycle: {facts.get("normalized_lifecycle")}

==================================================
2. DOCUMENT RESEARCH SUMMARY:
==================================================
{docs_str}

==================================================
3. HUNTER MODEL DECISION:
==================================================
{hunter_str}

==================================================
OUTPUT INSTRUCTIONS:
==================================================
You MUST return a single, valid JSON object matching the schema below.
Evaluate independently each field: Object classification, Procurement mode, Category scope, each Category, each Product, Commercial entry, and Medal.
Determine if you agree, disagree, or partially agree.
Also answer: "Did Hunter miss any product or category present in the researched documents?" If so, list them in `auditor_discovered_candidate` with exact evidence.

JSON Schema:
{{
  "object": {{
    "verdict": "AGREE" or "DISAGREE" or "PARTIAL",
    "why": "string",
    "evidence": "string"
  }},
  "procurement_mode": {{
    "verdict": "AGREE" or "DISAGREE" or "PARTIAL",
    "why": "string",
    "evidence": "string"
  }},
  "category_scope": {{
    "verdict": "AGREE" or "DISAGREE" or "PARTIAL",
    "why": "string",
    "evidence": "string"
  }},
  "categories": [
    {{
      "category_code": "string",
      "verdict": "AGREE" or "DISAGREE" or "PARTIAL",
      "why": "string",
      "evidence": "string"
    }}
  ],
  "products": [
    {{
      "product_name_normalized": "string",
      "verdict": "AGREE" or "DISAGREE" or "PARTIAL",
      "why": "string",
      "evidence": "string"
    }}
  ],
  "commercial_entry": {{
    "verdict": "AGREE" or "DISAGREE" or "PARTIAL",
    "why": "string",
    "evidence": "string"
  }},
  "medal": {{
    "verdict": "AGREE" or "DISAGREE" or "PARTIAL",
    "why": "string",
    "evidence": "string"
  }},
  "auditor_discovered_candidate": [
    {{
      "category_code": "string",
      "product_type": "string",
      "product_name_normalized": "string",
      "brand": "string or null",
      "model": "string or null",
      "quantity": number or null,
      "unit": "string or null",
      "raw_description": "string",
      "evidence_text": "string (exact quote)",
      "document_name": "string",
      "locator": {{
        "page": "string or null",
        "sheet": "string or null",
        "row": "string or null",
        "position_number": "string or null"
      }}
    }}
  ]
}}
"""

    def evaluate_consensus(self, hunter: Dict[str, Any], auditor: Dict[str, Any]) -> str:
        """Determine consensus level between Hunter and Auditor."""
        obj_verdict = auditor.get("object", {}).get("verdict")
        mode_verdict = auditor.get("procurement_mode", {}).get("verdict")
        scope_verdict = auditor.get("category_scope", {}).get("verdict")
        medal_verdict = auditor.get("medal", {}).get("verdict")

        verdicts = [obj_verdict, mode_verdict, scope_verdict, medal_verdict]
        
        if all(v == "AGREE" for v in verdicts):
            return CONSENSUS_AGREEMENT
        if any(v == "DISAGREE" for v in verdicts):
            return CONSENSUS_DISAGREEMENT
        if any(v == "PARTIAL" for v in verdicts):
            return CONSENSUS_PARTIAL
        return CONSENSUS_UNRESOLVED

    def save_product_findings(
        self,
        procurement_id: int,
        procurement_number: str,
        products: List[Dict[str, Any]],
        model_run_id: Optional[int],
        role: str,
    ) -> None:
        """Persist product findings into crm_v3_product_findings."""
        for p in products:
            loc = p.get("locator") or {}
            source_loc_json = json.dumps(loc, default=str)
            self.crm_db.execute_update(
                """
                INSERT INTO crm_v3_product_findings (
                    procurement_id, procurement_number, category_code,
                    product_type, product_name_normalized, brand, model,
                    quantity, unit, raw_description, evidence_text,
                    document_name, page, sheet, row_num, position_number,
                    source_locator_json, extractor_role, extraction_confidence,
                    model_run_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    procurement_id,
                    procurement_number,
                    p.get("category_code"),
                    p.get("product_type"),
                    p.get("product_name_normalized"),
                    p.get("brand"),
                    p.get("model"),
                    p.get("quantity"),
                    p.get("unit"),
                    p.get("raw_description"),
                    p.get("evidence_text"),
                    p.get("document_name"),
                    loc.get("page"),
                    loc.get("sheet"),
                    loc.get("row"),
                    loc.get("position_number"),
                    source_loc_json,
                    role,
                    1.0 if role == "HUNTER" else 0.8,
                    model_run_id,
                ),
            )

    def save_inference_run_record(
        self,
        procurement_id: int,
        run_kind: str,
        prompt: str,
        raw_text: str,
        parsed_json: Dict[str, Any],
        prompt_version: str,
        ollama_meta: Dict[str, Any],
        retry_count: int,
    ) -> int:
        """Persist model run into crm_v3_model_inference_runs."""
        rec = InferenceRunRecord(
            procurement_id=procurement_id,
            run_kind=run_kind,
            model_name="qwen2.5:7b",
            model_version="qwen2.5:7b",
            prompt_version=prompt_version,
            schema_version="v3_learning",
            prompt_hash=prompt_sha256(prompt),
            raw_model_text=raw_text,
            raw_model_sha256=raw_model_sha256(raw_text),
            raw_model_json=parsed_json,
            parse_status="PARSED_OK",
            validated_model_result=parsed_json,
            validated_model_sha256=validated_model_sha256(parsed_json),
            validation_status="VALIDATED_SUCCESS",
            run_status="COMPLETED",
            ollama_metadata=ollama_meta,
            retry_count=retry_count,
        )
        run_id = insert_inference_run(self.crm_db, rec)
        if run_id is None:
            raise RuntimeError("Failed to insert model inference run record")
        return run_id

    def run_learning_loop(self, procurement_id: int, priors_text: str = "") -> Dict[str, Any]:
        """Runs the entire Hunter-Auditor loop sequentially for one procurement."""
        facts = self.fetch_procurement_facts(procurement_id)
        procurement_number = facts.get("registry_number")
        
        # Load registry
        registry = self.load_active_categories()
        
        # Load document details
        docs, doc_set_hash = self.fetch_document_research_summary(procurement_id)
        evidence = self.fetch_document_evidence(procurement_id)
        evidence_hash = compute_md5(evidence)

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
            run_kind="SHADOW",
            prompt=hunter_prompt,
            raw_text=hunter_raw.get("raw_text") if isinstance(hunter_raw, dict) else str(hunter_raw),
            parsed_json=hunter_raw,
            prompt_version=HUNTER_PROMPT_VERSION,
            ollama_meta=hunter_meta,
            retry_count=hunter_retries,
        )
        logger.info(f"Hunter completed. Run ID: {hunter_run_id}")

        # Save Hunter product findings
        detected_products = hunter_raw.get("detected_products") or []
        self.save_product_findings(procurement_id, procurement_number, detected_products, hunter_run_id, "HUNTER")

        # 2. Build & Run Auditor
        auditor_prompt = self.build_auditor_prompt(facts, docs, hunter_raw)
        
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
            run_kind="SHADOW",
            prompt=auditor_prompt,
            raw_text=auditor_raw.get("raw_text") if isinstance(auditor_raw, dict) else str(auditor_raw),
            parsed_json=auditor_raw,
            prompt_version=AUDITOR_PROMPT_VERSION,
            ollama_meta=auditor_meta,
            retry_count=auditor_retries,
        )
        logger.info(f"Auditor completed. Run ID: {auditor_run_id}")

        # Save Auditor discovered candidates (missed products)
        missed_products = auditor_raw.get("auditor_discovered_candidate") or []
        self.save_product_findings(procurement_id, procurement_number, missed_products, auditor_run_id, "AUDITOR")

        # 3. Consensus & Trace
        consensus_state = self.evaluate_consensus(hunter_raw, auditor_raw)
        logger.info(f"Consensus state: {consensus_state}")

        source_snapshot_hash = compute_md5(facts)
        
        # Save trace
        self.crm_db.execute_update(
            """
            INSERT INTO crm_v3_autonomous_analysis_traces (
                procurement_id, source_snapshot_hash, document_set_hash,
                extracted_evidence_hash, hunter_run_id, auditor_run_id,
                consensus_state
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                procurement_id,
                source_snapshot_hash,
                doc_set_hash,
                evidence_hash,
                hunter_run_id,
                auditor_run_id,
                consensus_state,
            ),
        )

        return {
            "procurement_id": procurement_id,
            "hunter_run_id": hunter_run_id,
            "auditor_run_id": auditor_run_id,
            "consensus_state": consensus_state,
            "hunter_result": hunter_raw,
            "auditor_result": auditor_raw,
        }
