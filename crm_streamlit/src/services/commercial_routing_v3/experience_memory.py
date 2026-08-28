"""Experience memory layer for autonomous procurement analysis.

Tracks historical outcomes of categories based on:
- Observations (total enqueued/processed runs)
- Machine found (extracted products in findings)
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
            
            # 1. Total Observations
            q_obs = f"""
                SELECT COUNT(DISTINCT t.procurement_id)
                FROM crm_v3_autonomous_analysis_traces t
                JOIN crm_procurements p ON p.id = t.procurement_id
                WHERE {where_sql}
            """
            obs_count = self.crm_db.execute_scalar(q_obs, params) or 0
            
            # 2. Machine Present (machine_found)
            q_machine = f"""
                SELECT COUNT(DISTINCT f.procurement_id)
                FROM crm_v3_product_findings f
                JOIN crm_procurements p ON p.id = f.procurement_id
                WHERE {where_sql}
                  AND f.category_code = %s
            """
            machine_count = self.crm_db.execute_scalar(q_machine, params + [cat_code]) or 0

            # 3. Human confirmed count
            q_human = f"""
                SELECT COUNT(DISTINCT a.procurement_id)
                FROM crm_v3_expert_annotations a
                JOIN crm_procurements p ON p.id = a.procurement_id
                WHERE {where_sql}
                  AND a.is_current = TRUE
                  AND (a.payload->'expert_category_scope'->>'verdict' = 'IN_CATEGORY' OR a.payload->>'expert_verdict' = 'CORRECT')
                  AND (a.payload->'expert_category_scope'->'categories' @> %s::jsonb OR a.payload->>'expert_medal' != 'NCE')
            """
            human_confirmed = self.crm_db.execute_scalar(q_human, params + [f'["{cat_code}"]']) or 0

            # 4. Human rejected count
            q_rejected = f"""
                SELECT COUNT(DISTINCT a.procurement_id)
                FROM crm_v3_expert_annotations a
                JOIN crm_procurements p ON p.id = a.procurement_id
                JOIN crm_v3_product_findings f ON f.procurement_id = a.procurement_id
                WHERE {where_sql}
                  AND a.is_current = TRUE
                  AND f.category_code = %s
                  AND (
                      a.payload->'expert_category_scope'->>'verdict' = 'OUT_OF_CATEGORY'
                      OR a.payload->>'expert_verdict' = 'WRONG'
                  )
            """
            human_rejected = self.crm_db.execute_scalar(q_rejected, params + [cat_code]) or 0

            # 5. Auditor confirmed count
            q_auditor = f"""
                SELECT COUNT(DISTINCT t.procurement_id)
                FROM crm_v3_autonomous_analysis_traces t
                JOIN crm_procurements p ON p.id = t.procurement_id
                JOIN crm_v3_model_inference_runs r ON r.id = t.auditor_run_id
                WHERE {where_sql}
                  AND r.validated_model_result->'categories' @> %s::jsonb
            """
            auditor_confirmed = self.crm_db.execute_scalar(q_auditor, params + [f'[{{"category_code": "{cat_code}", "verdict": "AGREE"}}]']) or 0

            # 6. Not found after complete research (traces with 0 product findings for this category AND research is COMPLETE)
            q_not_found = f"""
                SELECT COUNT(DISTINCT t.procurement_id)
                FROM crm_v3_autonomous_analysis_traces t
                JOIN crm_procurements p ON p.id = t.procurement_id
                WHERE {where_sql}
                  AND COALESCE(t.research_completeness, 'COMPLETE') = 'COMPLETE'
                  AND NOT EXISTS (
                      SELECT 1 FROM crm_v3_product_findings f 
                      WHERE f.procurement_id = t.procurement_id AND f.category_code = %s
                  )
            """
            not_found_complete = self.crm_db.execute_scalar(q_not_found, params + [cat_code]) or 0

            # 7. Unknown due to incomplete research (traces with 0 product findings for this category AND research is PARTIAL)
            q_partial = f"""
                SELECT COUNT(DISTINCT t.procurement_id)
                FROM crm_v3_autonomous_analysis_traces t
                JOIN crm_procurements p ON p.id = t.procurement_id
                WHERE {where_sql}
                  AND COALESCE(t.research_completeness, 'COMPLETE') = 'PARTIAL'
                  AND NOT EXISTS (
                      SELECT 1 FROM crm_v3_product_findings f 
                      WHERE f.procurement_id = t.procurement_id AND f.category_code = %s
                  )
            """
            unknown_partial = self.crm_db.execute_scalar(q_partial, params + [cat_code]) or 0

            stats_list.append({
                "category_code": cat_code,
                "category_name": cat["category_name"],
                "observations": obs_count,
                "machine_found": machine_count,
                "auditor_confirmed": auditor_confirmed,
                "human_confirmed": human_confirmed,
                "human_rejected": human_rejected,
                "not_found_complete": not_found_complete,
                "unknown_partial": unknown_partial,
            })
            
        return stats_list
