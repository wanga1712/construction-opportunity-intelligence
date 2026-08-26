#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.annotation_category_gate import (
    IN_CATEGORY,
    OUT_OF_CATEGORY,
    UNCERTAIN,
    first_stage_dataset_rows,
)
from src.services.annotation_state_service import annotation_state_counts, load_current_annotation_states
from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.db_bootstrap import connect_databases

_, _, crm, _ = connect_databases()
where = "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND " + actionable_submission_sql("cp")
ids = [r["id"] for r in crm.execute_query(f"SELECT cp.id FROM crm_procurements cp WHERE {where}")]
states = load_current_annotation_states(ids, crm)
counts = annotation_state_counts(states)
rows = first_stage_dataset_rows(crm, limit=50)
print(
    json.dumps(
        {
            "TORGI_ALL": counts["ALL"],
            "TORGI_UNREVIEWED": counts["UNREVIEWED"],
            "TORGI_REVIEWED": counts["REVIEWED"],
            "TORGI_IN_CATEGORY": counts.get(IN_CATEGORY, 0),
            "TORGI_OUT_OF_CATEGORY": counts.get(OUT_OF_CATEGORY, 0),
            "TORGI_UNCERTAIN": counts.get(UNCERTAIN, 0),
            "FIRST_STAGE_REVIEWED_COUNT": len(rows),
            "FIRST_STAGE_IN_CATEGORY": sum(1 for r in rows if r["expert_category_scope"] == IN_CATEGORY),
            "FIRST_STAGE_OUT_OF_CATEGORY": sum(1 for r in rows if r["expert_category_scope"] == OUT_OF_CATEGORY),
            "FIRST_STAGE_UNCERTAIN": sum(1 for r in rows if r["expert_category_scope"] == UNCERTAIN),
            "LEGACY_NEGATIVE_TOTAL": counts.get("LEGACY_NOT_INTERESTING", 0),
            "dataset_sample": rows[:5],
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )
)
