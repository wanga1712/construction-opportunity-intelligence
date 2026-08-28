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
            SELECT id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table
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
        
        ann_id = None
        annotation = None
        if ann_rows:
            row = ann_rows[0]
            ann_id = row["id"]
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
            expert_mode = annotation.get("expert_procurement_mode") or annotation.get("expert_procurement_form")
            expert_scope_val = annotation.get("expert_scope_verdict")
            if not expert_scope_val and isinstance(annotation.get("expert_category_scope"), dict):
                expert_scope_val = annotation.get("expert_category_scope", {}).get("verdict")
            expert_medal = annotation.get("expert_commercial_medal") or annotation.get("expert_medal")

            # Compile Object classification
            if expert_obj:
                targets["object_type"] = {
                    "value": expert_obj,
                    "label_source": "HUMAN_ANNOTATED",
                    "human_action_id": annotation.get("human_action_id"),
                    "annotation_id": ann_id
                }

            # Compile Procurement Mode
            if expert_mode:
                targets["procurement_mode"] = {
                    "value": expert_mode,
                    "label_source": "HUMAN_ANNOTATED",
                    "human_action_id": annotation.get("human_action_id"),
                    "annotation_id": ann_id
                }

            # Compile Category Scope
            if expert_scope_val:
                if expert_scope_val in {"IN_CATEGORY", "OUT_OF_CATEGORY", "UNCERTAIN"}:
                    targets["category_scope"] = {
                        "value": expert_scope_val,
                        "label_source": "HUMAN_ANNOTATED",
                        "human_action_id": annotation.get("human_action_id"),
                        "annotation_id": ann_id
                    }
                else:
                    targets["category_scope_legacy_provenance"] = {
                        "value": expert_scope_val,
                        "label_source": "HUMAN_ANNOTATED",
                        "human_action_id": annotation.get("human_action_id"),
                        "annotation_id": ann_id
                    }

            # Compile Medal
            if expert_medal:
                if expert_medal in {"GOLD", "SILVER", "BRONZE", "WOOD"}:
                    targets["medal"] = {
                        "value": expert_medal,
                        "label_source": "HUMAN_ANNOTATED",
                        "human_action_id": annotation.get("human_action_id"),
                        "annotation_id": ann_id
                    }
                else:
                    targets["medal_legacy_provenance"] = {
                        "value": expert_medal,
                        "label_source": "HUMAN_ANNOTATED",
                        "human_action_id": annotation.get("human_action_id"),
                        "annotation_id": ann_id
                    }

        source_tbl = str(facts.get("source_table") or "").lower()
        law_type = "44-FZ"
        if "223" in source_tbl:
            law_type = "223-FZ"
        elif "615" in source_tbl:
            law_type = "615-PP"

        # 5. Build full dataset entry
        entry = {
            "procurement_id": procurement_id,
            "registry_number": facts.get("contract_number"),
            "factual_source": {
                "law_type": law_type,
                "title": facts.get("auction_name"),
                "official_description": "",
                "okpd_code": facts.get("okpd_code"),
                "okpd_name": facts.get("okpd_name"),
            },
            "sparse_targets": targets,
            "compiled_at": None
        }
        
        logger.info(f"[DatasetCompiler] Target compiled for procurement {procurement_id}: targets={list(targets.keys())}")
        return entry
