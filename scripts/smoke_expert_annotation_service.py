"""One-shot S13 acceptance smoke for expert annotation service.

Uses an isolated negative procurement id and a unique created_by marker.
The caller must clean those exact rows after recording the PASS output.
"""
from __future__ import annotations

import json

from config.settings import Settings
from modules.crm.crm_database import CrmDatabaseManager

from src.services.expert_annotation_service import (
    collect_expert_object_types,
    collect_expert_work_stages,
    load_expert_annotation,
    save_expert_annotation,
    save_taxonomy_proposal,
    write_audit_row,
)


PROCUREMENT_ID = -17081701
MARKER = "codex_expert_annotation_smoke_20260817"
OBJECT_VALUE = "мост smoke 20260817"
STAGE_VALUE = "ремонт smoke 20260817"
PROPOSAL_NAME = "smoke taxonomy proposal 20260817"


def _scalar(db: CrmDatabaseManager, sql: str, params=()):
    rows = db.execute_query(sql, params)
    return next(iter(rows[0].values())) if rows else None


def _model_digest(db: CrmDatabaseManager) -> str | None:
    return _scalar(
        db,
        """
        SELECT md5(string_agg(
            id::text || ':' || COALESCE(normalized_result::text, ''),
            '|' ORDER BY id
        )) AS digest
        FROM procurement_ai_assessments
        """,
    )


def _base_payload(verdict: str) -> dict:
    return {
        "model_assessment_id": None,
        "expert_verdict": verdict,
        "expert_procurement_form": "CONSTRUCTION_WORKS",
        "expert_object_type": OBJECT_VALUE,
        "expert_object_subtype": "ремонтируемый мост",
        "expert_work_stage": STAGE_VALUE,
        "expert_commercial_verdict": "ACTIONABLE",
        "expert_medal": "WOOD",
        "medal_reason": "INSUFFICIENT_TIME",
        "medal_comment": "service smoke",
        "error_reasons": ["WRONG_CATEGORY_PRIORITY"],
        "expert_comment": "isolated service smoke",
        "opportunities": [],
        "rejected_model_opportunities": [],
        "taxonomy_proposals": [],
        "created_by": MARKER,
    }


def main() -> None:
    settings = Settings()
    db = CrmDatabaseManager(settings.crm_database)
    db.connect(fallback_to_offline=False)
    try:
        endpoint = db.execute_query(
            "SELECT inet_server_addr()::text AS host, inet_server_port() AS port, current_database() AS db"
        )[0]
        print(json.dumps({"connected_endpoint": endpoint}, ensure_ascii=False))
        assert not load_expert_annotation(PROCUREMENT_ID, db), "smoke id already used"
        model_before = _model_digest(db)
        categories_before = _scalar(db, "SELECT count(*) FROM crm_product_categories")

        correct = _base_payload("CORRECT")
        correct["error_reasons"] = []
        correct_id = save_expert_annotation(PROCUREMENT_ID, correct, MARKER, db)
        db.disconnect()
        db.connect(fallback_to_offline=False)
        assert load_expert_annotation(PROCUREMENT_ID, db)["payload"]["expert_verdict"] == "CORRECT"

        wrong = _base_payload("WRONG")
        wrong_id = save_expert_annotation(PROCUREMENT_ID, wrong, MARKER, db)
        db.disconnect()
        db.connect(fallback_to_offline=False)
        assert load_expert_annotation(PROCUREMENT_ID, db)["payload"]["expert_verdict"] == "WRONG"

        partial = _base_payload("PARTIALLY_CORRECT")
        partial["opportunities"] = [
            {
                "expert_rank": 1,
                "expert_action": "ADD",
                "category_code": "concrete_repair",
                "subcategory_code": None,
                "opportunity_track": "EMBEDDED_MATERIAL",
                "hypothesis_reasons": ["EXPERT_COMMERCIAL_KNOWLEDGE"],
                "expected_document_sources": ["ESTIMATE"],
                "model_opportunity_snapshot": None,
                "model_opportunity_index": None,
                "comment": "rank one",
            },
            {
                "expert_rank": 2,
                "expert_action": "MODIFY",
                "category_code": "waterproofing",
                "subcategory_code": None,
                "opportunity_track": "DESIGN_REQUIREMENT",
                "hypothesis_reasons": ["EXPECTED_IN_PROJECT_DOCUMENTATION"],
                "expected_document_sources": ["PROJECT_DOCUMENTATION"],
                "model_opportunity_snapshot": {"category_code": "wrong_model_category"},
                "model_opportunity_index": 0,
                "comment": "rank two",
            },
        ]
        partial["rejected_model_opportunities"] = [
            {
                "expert_rank": None,
                "expert_action": "REJECT",
                "category_code": "wrong_model_category",
                "subcategory_code": None,
                "opportunity_track": "DIRECT_SUPPLY",
                "rejection_reason": "FALSE_POSITIVE",
                "model_opportunity_snapshot": {"category_code": "wrong_model_category"},
                "model_opportunity_index": 0,
                "comment": "negative label",
            }
        ]
        partial_id = save_expert_annotation(PROCUREMENT_ID, partial, MARKER, db)
        db.disconnect()
        db.connect(fallback_to_offline=False)
        loaded = load_expert_annotation(PROCUREMENT_ID, db)["payload"]
        assert loaded["expert_verdict"] == "PARTIALLY_CORRECT"
        assert loaded["expert_procurement_form"] == "CONSTRUCTION_WORKS"
        assert loaded["expert_medal"] == "WOOD"
        assert loaded["medal_reason"] == "INSUFFICIENT_TIME"
        assert [item["expert_rank"] for item in loaded["opportunities"]] == [1, 2]
        assert loaded["rejected_model_opportunities"][0]["expert_action"] == "REJECT"
        assert OBJECT_VALUE in collect_expert_object_types(db)
        assert STAGE_VALUE in collect_expert_work_stages(db)

        proposal = {
            "proposal_type": "CATEGORY",
            "proposed_name": PROPOSAL_NAME,
            "proposed_parent_category": "bridge",
            "expert_comment": "must remain pending",
        }
        save_taxonomy_proposal(PROCUREMENT_ID, partial_id, proposal, MARKER, db)
        proposal_status = _scalar(
            db,
            """
            SELECT review_status FROM crm_v3_taxonomy_proposals
            WHERE procurement_id = %s AND created_by = %s
            """,
            (PROCUREMENT_ID, MARKER),
        )
        assert proposal_status == "PENDING"

        write_audit_row(PROCUREMENT_ID, {"immutable": "MODEL_V0"}, partial, db)
        audit_count = _scalar(
            db,
            """
            SELECT count(*) FROM crm_manual_assessments_audit
            WHERE procurement_id = %s
              AND corrected_value->>'created_by' = %s
            """,
            (PROCUREMENT_ID, MARKER),
        )
        assert audit_count == 1
        assert _model_digest(db) == model_before
        assert _scalar(db, "SELECT count(*) FROM crm_product_categories") == categories_before
        canonical_name_count = _scalar(
            db,
            "SELECT count(*) FROM crm_product_categories WHERE category_name = %s",
            (PROPOSAL_NAME,),
        )
        assert canonical_name_count == 0

        print(json.dumps({
            "SERVICE_SMOKE": "PASS",
            "db_endpoint": endpoint,
            "procurement_id": PROCUREMENT_ID,
            "annotation_ids": [correct_id, wrong_id, partial_id],
            "wrong_reload": "WRONG",
            "partial_reload": "PARTIALLY_CORRECT",
            "ranks": [1, 2],
            "negative_label": "REJECT",
            "expert_form": loaded["expert_procurement_form"],
            "expert_object_suggestion": OBJECT_VALUE,
            "expert_stage_suggestion": STAGE_VALUE,
            "expert_medal": loaded["expert_medal"],
            "medal_reason": loaded["medal_reason"],
            "taxonomy_status": proposal_status,
            "audit_count": audit_count,
            "model_raw_preserved": True,
            "canonical_taxonomy_unchanged": True,
        }, ensure_ascii=False, indent=2))
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()
