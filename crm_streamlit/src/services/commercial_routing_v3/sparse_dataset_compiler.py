"""Sparse dataset compiler for autonomous learning loop.

Gathers source facts, document evidence, and human annotations, compiling them
into canonical training targets for model calibration and LoRA adapter training.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("commercial_routing_v3.sparse_dataset_compiler")

class SparseDatasetCompiler:
    """Compiles training target entries with strict provenance (no fabricated data)."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def compile_target(self, procurement_id: int) -> Optional[Dict[str, Any]]:
        """Compile a canonical training target for the given procurement.

        Integrates:
        - Source facts (FACTUAL_SOURCE)
        - Current expert human annotation (HUMAN_CONFIRMED or HUMAN_CORRECTED)
        - Extracted document evidence (if present)
        """
        # 1. Load procurement facts
        facts_rows = self.crm_db.execute_query(
            """
            SELECT id, law_type, registry_number, title, official_description, okpd_code, okpd_name
            FROM crm_procurements
            WHERE id = %s
            """,
            (procurement_id,),
        )
        if not facts_rows:
            return None
        facts = dict(facts_rows[0])

        # 2. Load latest expert annotation
        ann_rows = self.crm_db.execute_query(
            """
            SELECT id, payload
            FROM crm_v3_expert_annotations
            WHERE procurement_id = %s AND is_current = TRUE
            LIMIT 1
            """,
            (procurement_id,),
        )
        
        annotation = None
        if ann_rows:
            row = ann_rows[0]
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            annotation = payload

        # 3. Load latest trace to identify Hunter/Auditor values
        trace_rows = self.crm_db.execute_query(
            """
            SELECT hunter_run_id, auditor_run_id, consensus_state
            FROM crm_v3_autonomous_analysis_traces
            WHERE procurement_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (procurement_id,),
        )
        
        trace = dict(trace_rows[0]) if trace_rows else {}

        # 4. Construct sparse labels
        targets: Dict[str, Any] = {}
        
        if annotation:
            # We map human confirmations and corrections.
            # E.g. expert_object_type, expert_procurement_mode, expert_category_scope, expert_commercial_medal
            expert_obj = annotation.get("expert_object_type")
            expert_mode = annotation.get("expert_procurement_mode")
            expert_scope = annotation.get("expert_category_scope") or {}
            expert_medal = annotation.get("expert_commercial_medal")

            # We fetch model values to determine if confirmed or corrected
            hunter_run_id = trace.get("hunter_run_id")
            hunter_result = {}
            if hunter_run_id:
                hr_rows = self.crm_db.execute_query(
                    "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id = %s",
                    (hunter_run_id,),
                )
                if hr_rows:
                    hunter_result = hr_rows[0].get("validated_model_result") or {}

            # Compile Object classification
            if expert_obj:
                model_obj = hunter_result.get("object_type")
                targets["object_type"] = {
                    "value": expert_obj,
                    "label_source": "HUMAN_CONFIRMED" if expert_obj == model_obj else "HUMAN_CORRECTED"
                }

            # Compile Procurement Mode
            if expert_mode:
                model_mode = hunter_result.get("procurement_mode")
                targets["procurement_mode"] = {
                    "value": expert_mode,
                    "label_source": "HUMAN_CONFIRMED" if expert_mode == model_mode else "HUMAN_CORRECTED"
                }

            # Compile Category Scope
            if expert_scope.get("verdict"):
                val = expert_scope.get("verdict")
                model_val = hunter_result.get("category_scope")
                targets["category_scope"] = {
                    "value": val,
                    "label_source": "HUMAN_CONFIRMED" if val == model_val else "HUMAN_CORRECTED"
                }

            # Compile Medal
            if expert_medal:
                model_medal = hunter_result.get("medal_hypothesis")
                targets["medal"] = {
                    "value": expert_medal,
                    "label_source": "HUMAN_CONFIRMED" if expert_medal == model_medal else "HUMAN_CORRECTED"
                }

        # 5. Build full dataset entry
        entry = {
            "procurement_id": procurement_id,
            "registry_number": facts.get("registry_number"),
            "factual_source": {
                "law_type": facts.get("law_type"),
                "title": facts.get("title"),
                "official_description": facts.get("official_description"),
                "okpd_code": facts.get("okpd_code"),
                "okpd_name": facts.get("okpd_name"),
            },
            "sparse_targets": targets,
            "compiled_at": None
        }
        
        logger.info(f"[DatasetCompiler] Target compiled for procurement {procurement_id}: targets={list(targets.keys())}")
        return entry
