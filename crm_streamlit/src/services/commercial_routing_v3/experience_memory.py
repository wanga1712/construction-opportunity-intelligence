"""Experience memory layer for autonomous procurement analysis.

Tracks historical outcomes of categories based on:
- Machine found
- Auditor confirmed
- Human confirmed
- Human rejected
- Not found after complete research
- Unknown due to incomplete research
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("commercial_routing_v3.experience_memory")

class ExperienceMemory:
    """Provides historical statistical priors based on past runs and human validation."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def get_category_stats(
        self,
        *,
        object_sector: Optional[str] = None,
        object_type: Optional[str] = None,
        object_subtype: Optional[str] = None,
        procurement_mode: Optional[str] = None,
        okpd_prefix: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return statistics for each category matching the filters."""
        # For simplicity and flexibility, we query the trace and observation records
        # and aggregate on the fly.
        
        # Build filter clause
        where_clauses = []
        params = []
        if object_sector:
            where_clauses.append("p.object_sector = %s")
            params.append(object_sector)
        if object_type:
            where_clauses.append("p.object_type = %s")
            params.append(object_type)
        if object_subtype:
            where_clauses.append("p.object_subtype = %s")
            params.append(object_subtype)
        if procurement_mode:
            where_clauses.append("p.procurement_mode = %s")
            params.append(procurement_mode)
        if okpd_prefix:
            where_clauses.append("p.okpd_code LIKE %s")
            params.append(f"{okpd_prefix}%")

        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

        # Query all active categories to make sure they are represented
        categories = self.crm_db.execute_query(
            "SELECT category_code, category_name FROM crm_product_categories WHERE is_active = TRUE"
        ) or []

        stats_list = []
        for cat in categories:
            cat_code = cat["category_code"]
            
            # 1. Machine found count
            # Count how many times the category was matched in document observations or product findings
            q_machine = f"""
                SELECT COUNT(DISTINCT o.procurement_id)
                FROM crm_v3_document_observations o
                JOIN crm_procurements p ON p.id = o.procurement_id
                WHERE {where_sql}
                  AND (o.matched_categories @> %s::jsonb OR EXISTS (
                      SELECT 1 FROM crm_v3_product_findings f 
                      WHERE f.procurement_id = o.procurement_id AND f.category_code = %s
                  ))
            """
            machine_count = self.crm_db.execute_scalar(q_machine, params + [f'["{cat_code}"]', cat_code]) or 0

            # 2. Human confirmed count
            # Count how many times the category was present in current expert annotations
            q_human = f"""
                SELECT COUNT(DISTINCT a.procurement_id)
                FROM crm_v3_expert_annotations a
                JOIN crm_procurements p ON p.id = a.procurement_id
                WHERE {where_sql}
                  AND a.is_current = TRUE
                  AND a.payload->'expert_category_scope'->>'verdict' = 'IN_CATEGORY'
                  AND a.payload->'expert_category_scope'->'categories' @> %s::jsonb
            """
            human_confirmed = self.crm_db.execute_scalar(q_human, params + [f'["{cat_code}"]']) or 0

            # 3. Human rejected count
            # Found by model but rejected by human (scope OUT_OF_CATEGORY or category not in selected)
            q_rejected = f"""
                SELECT COUNT(DISTINCT a.procurement_id)
                FROM crm_v3_expert_annotations a
                JOIN crm_procurements p ON p.id = a.procurement_id
                JOIN crm_v3_document_observations o ON o.procurement_id = a.procurement_id
                WHERE {where_sql}
                  AND a.is_current = TRUE
                  AND (o.matched_categories @> %s::jsonb)
                  AND (
                      a.payload->'expert_category_scope'->>'verdict' = 'OUT_OF_CATEGORY'
                      OR NOT (a.payload->'expert_category_scope'->'categories' @> %s::jsonb)
                  )
            """
            human_rejected = self.crm_db.execute_scalar(q_rejected, params + [f'["{cat_code}"]', f'["{cat_code}"]']) or 0

            # 4. Auditor confirmed count
            # Consensus AGREEMENT or PARTIAL and auditor agreed
            q_auditor = f"""
                SELECT COUNT(DISTINCT t.procurement_id)
                FROM crm_v3_autonomous_analysis_traces t
                JOIN crm_procurements p ON p.id = t.procurement_id
                JOIN crm_v3_model_inference_runs r ON r.id = t.auditor_run_id
                WHERE {where_sql}
                  AND r.validated_model_result->'categories' @> %s::jsonb
            """
            auditor_confirmed = self.crm_db.execute_scalar(q_auditor, params + [f'[{{"category_code": "{cat_code}", "verdict": "AGREE"}}]']) or 0

            # 5. Not found after complete research
            # Count procurements where all resolved docs are searched and no evidence of category found
            q_not_found = f"""
                SELECT COUNT(DISTINCT o.procurement_id)
                FROM crm_v3_document_observations o
                JOIN crm_procurements p ON p.id = o.procurement_id
                WHERE {where_sql}
                  AND NOT (o.matched_categories @> %s::jsonb)
                  AND o.usefulness_label = 'PARSED_NO_COMMERCIAL_EVIDENCE'
            """
            not_found_complete = self.crm_db.execute_scalar(q_not_found, params + [f'["{cat_code}"]']) or 0

            stats_list.append({
                "category_code": cat_code,
                "category_name": cat["category_name"],
                "machine_found": machine_count,
                "auditor_confirmed": auditor_confirmed,
                "human_confirmed": human_confirmed,
                "human_rejected": human_rejected,
                "not_found_complete": not_found_complete,
                "unknown_partial": max(0, machine_count - human_confirmed - human_rejected),
            })
            
        return stats_list
