#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)
from src.services.db_bootstrap import connect_databases
from src.services.expert_annotation_service import load_model_assessment_for_annotation
from src.services.commercial_routing_v3.model_ui_projection import (
    business_view_from_assessment,
    model_view_from_assessment,
)

_radar, tender, crm, _ = connect_databases()
a = load_model_assessment_for_annotation(720, crm)
mv = model_view_from_assessment(a)
bv = business_view_from_assessment(a)
print(
    "PROVEN",
    a.get("inference_run_id"),
    mv.get("provenance"),
    mv.get("object_type"),
    bv.get("provenance"),
    bv.get("business_candidate_medal"),
)
rows = crm.execute_query(
    "SELECT procurement_id FROM procurement_ai_assessments WHERE is_current AND inference_run_id IS NULL LIMIT 1"
)
pid = rows[0]["procurement_id"]
b = load_model_assessment_for_annotation(pid, crm)
mv2 = model_view_from_assessment(b)
print("LEGACY", pid, b.get("inference_run_id"), mv2.get("provenance"))
print(
    "PROVEN_ASSESSMENTS",
    crm.execute_scalar(
        "SELECT count(*) FROM procurement_ai_assessments WHERE is_current AND inference_run_id IS NOT NULL"
    ),
)
print(
    "PROD_RUNS",
    crm.execute_scalar(
        "SELECT count(*) FROM crm_v3_model_inference_runs WHERE run_kind=%s",
        ("PRODUCTION",),
    ),
)
print("PROVEN_MODEL_UI_MATCH", mv.get("provenance") == "MODEL_VALIDATED")
print("LEGACY_UI_PROVENANCE_CORRECT", mv2.get("provenance") == "UNKNOWN_LEGACY")
