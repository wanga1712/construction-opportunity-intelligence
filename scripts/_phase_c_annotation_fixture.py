#!/usr/bin/env python3
"""Isolated S13 save/reload/edit acceptance using a session-local temp table."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path[:0] = [str(ROOT), "/opt/pythonProject89"]

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.expert_annotation_service import load_expert_annotation, save_expert_annotation


def _model_hash(crm_db, procurement_id: int) -> str:
    rows = crm_db.execute_query(
        """
        SELECT normalized_result, business_rule_result, field_provenance
        FROM procurement_ai_assessments
        WHERE procurement_id=%s AND is_current=TRUE
        """,
        (procurement_id,),
    )
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    _, _, crm_db, _ = connect_databases()
    crm_db._ensure_connection()
    procurement_id = 18555
    before_count = crm_db.execute_scalar("SELECT count(*) FROM public.crm_v3_expert_annotations")
    before_hash = _model_hash(crm_db, procurement_id)
    crm_db.execute_update(
        "CREATE TEMP TABLE crm_v3_expert_annotations "
        "(LIKE public.crm_v3_expert_annotations INCLUDING DEFAULTS) ON COMMIT PRESERVE ROWS"
    )
    first = {
        "model_assessment_id": 1,
        "annotation_review_scope": "CATEGORY_ONLY",
        "annotation_completeness": "PARTIAL",
        "evidence_state": "NEEDS_DOCUMENT_RESEARCH",
        "fixture": True,
    }
    save_expert_annotation(procurement_id, first, "PHASE_C_ISOLATED_FIXTURE", crm_db)
    loaded_first = load_expert_annotation(procurement_id, crm_db)
    second = dict(first, annotation_completeness="COMPLETE", evidence_state="SUFFICIENT")
    save_expert_annotation(procurement_id, second, "PHASE_C_ISOLATED_FIXTURE", crm_db)
    loaded_second = load_expert_annotation(procurement_id, crm_db)
    crm_db.execute_update("DROP TABLE pg_temp.crm_v3_expert_annotations")
    after_count = crm_db.execute_scalar("SELECT count(*) FROM public.crm_v3_expert_annotations")
    after_hash = _model_hash(crm_db, procurement_id)
    result = {
        "save_works": loaded_first["payload"] == dict(first, schema_version=1),
        "reload_preserves_annotation": loaded_first["annotation_version"] == 1,
        "edit_works": loaded_second["payload"] == dict(second, schema_version=1),
        "second_reload_preserves_edit": loaded_second["annotation_version"] == 2,
        "production_annotation_count_unchanged": before_count == after_count,
        "model_fields_unchanged": before_hash == after_hash,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
