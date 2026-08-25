"""Read-only production audit for the guided expert taxonomy WIP."""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from src.bootstrap import setup_source_path

setup_source_path()

from config.settings import Settings  # noqa: E402
from modules.crm.crm_database import CrmDatabaseManager  # noqa: E402


def main() -> None:
    db = CrmDatabaseManager(Settings().crm_database)
    db.connect()
    schema = db.execute_query(
        """
        SELECT table_name,column_name,data_type
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name IN ('crm_product_categories','crm_product_subcategories')
        ORDER BY table_name,ordinal_position
        """
    ) or []
    print(json.dumps({"registry_schema": schema}, ensure_ascii=False, default=str, indent=2))
    categories = db.execute_query(
        """
        SELECT c.category_code, c.category_name,
               count(s.subcategory_code)::int AS subcategory_count
        FROM crm_product_categories c
        LEFT JOIN crm_product_subcategories s ON s.category_id=c.id AND s.is_active=TRUE
        WHERE c.is_active=TRUE
        GROUP BY c.category_code,c.category_name,c.sort_order
        ORDER BY c.sort_order,c.category_code
        """
    ) or []
    vocabulary = db.execute_query(
        """
        SELECT
          count(DISTINCT NULLIF(lower(regexp_replace(btrim(payload->>'expert_object_type'), '[[:space:]]+', ' ', 'g')), ''))::int AS object_types,
          count(DISTINCT NULLIF(lower(regexp_replace(btrim(payload->>'expert_object_subtype'), '[[:space:]]+', ' ', 'g')), ''))::int AS object_subtypes,
          count(DISTINCT NULLIF(lower(regexp_replace(btrim(payload->>'expert_work_stage'), '[[:space:]]+', ' ', 'g')), ''))::int AS work_stages
        FROM crm_v3_expert_annotations WHERE is_current=TRUE
        """
    ) or []
    proposals = db.execute_query(
        """
        SELECT review_status, proposal_type, count(*)::int AS count
        FROM crm_v3_taxonomy_proposals
        GROUP BY review_status,proposal_type ORDER BY review_status,proposal_type
        """
    ) or []
    negatives = db.execute_query(
        """
        SELECT procurement_id, payload->>'expert_scope_verdict' AS scope,
               payload->>'expert_medal' AS medal
        FROM crm_v3_expert_annotations
        WHERE is_current=TRUE AND payload->>'expert_scope_verdict'='OUT_OF_PROFILE'
        ORDER BY id
        """
    ) or []
    visible_controls = db.execute_query(
        """
        SELECT cp.id,cp.auction_name,cp.okpd_code,cp.okpd_name,
               array_remove(array_agg(DISTINCT o.commercial_category_code),NULL) AS categories,
               bool_or(ea.id IS NOT NULL) AS already_annotated
        FROM crm_procurements cp
        LEFT JOIN crm_procurement_category_opportunities o
          ON o.procurement_id=cp.id AND o.status='CURRENT'
        LEFT JOIN crm_v3_expert_annotations ea
          ON ea.procurement_id=cp.id AND ea.is_current=TRUE
        WHERE cp.id = ANY(%s)
        GROUP BY cp.id
        ORDER BY cp.id
        """,
        ([64132,64136,64197,63889,63912],),
    ) or []
    positive = db.execute_query(
        """
        SELECT cp.id, cp.auction_name, cp.okpd_code, cp.okpd_name,
               cp.ai_assessment_status,
               o.commercial_category_code
        FROM crm_procurements cp
        LEFT JOIN crm_procurement_category_opportunities o
          ON o.procurement_id=cp.id AND o.status='CURRENT'
        LEFT JOIN crm_v3_expert_annotations ea
          ON ea.procurement_id=cp.id AND ea.is_current=TRUE
        WHERE cp.id=64132 AND ea.id IS NULL
        """
    ) or []
    print(json.dumps({
        "active_category_count": len(categories),
        "active_subcategory_count": sum(int(row["subcategory_count"]) for row in categories),
        "categories": categories,
        "vocabulary": vocabulary[0] if vocabulary else {},
        "proposal_counts": proposals,
        "current_out_of_profile": negatives,
        "visible_control_candidates": visible_controls,
        "positive_control": positive[0] if positive else None,
        "positive_control_page": 100,
    }, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
