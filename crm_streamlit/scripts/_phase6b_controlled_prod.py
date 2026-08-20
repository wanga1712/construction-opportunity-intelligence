#!/usr/bin/env python3
"""Phase 6B controlled PRODUCTION inference (bounded IDs)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

os.environ["CRM_V3_QWEN_SHADOW_MODE"] = "0"
os.environ["CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED"] = "1"
os.environ["COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN"] = "1"
os.environ["COMMERCIAL_ROUTING_V3_RUNTIME_ENABLED"] = "1"

from src.services.db_bootstrap import connect_databases
from src.services.crm_ai_assessment_runner import run_live

IDS = [720, 886, 949, 975, 1016, 8003, 8175, 1, 840, 13248, 21782, 10795]


def main() -> int:
    _radar, tender_db, crm_db, _warn = connect_databases()
    results = []
    for pid in IDS:
        o_before = int(
            crm_db.execute_scalar(
                "SELECT count(*) FROM crm_procurement_category_opportunities WHERE procurement_id=%s AND status='CURRENT'",
                (pid,),
            )
            or 0
        )
        stats = run_live(
            tender_db,
            crm_db,
            limit=1,
            procurement_id=pid,
            force_reassess=True,
            reassess_reason="phase6b_controlled_prod",
            produce_s13_queue=False,
        )
        a_after = crm_db.execute_query(
            "SELECT id, inference_run_id, status FROM procurement_ai_assessments WHERE procurement_id=%s AND is_current LIMIT 1",
            (pid,),
        )
        o_after = int(
            crm_db.execute_scalar(
                "SELECT count(*) FROM crm_procurement_category_opportunities WHERE procurement_id=%s AND status='CURRENT'",
                (pid,),
            )
            or 0
        )
        irid = a_after[0].get("inference_run_id") if a_after else None
        run = None
        if irid:
            rr = crm_db.execute_query(
                "SELECT id, run_kind, raw_model_sha256 IS NOT NULL AS has_raw, validated_model_result IS NOT NULL AS has_val, validation_status FROM crm_v3_model_inference_runs WHERE id=%s",
                (irid,),
            )
            run = dict(rr[0]) if rr else None
        rec = {
            "procurement_id": pid,
            "run_live": stats,
            "inference_run_id": irid,
            "run": run,
            "opportunities_unchanged": o_before == o_after,
            "assessment_id": a_after[0]["id"] if a_after else None,
        }
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False, default=str), flush=True)

    linked = [r for r in results if r.get("inference_run_id")]
    prod = [r for r in linked if r.get("run") and r["run"].get("run_kind") == "PRODUCTION"]
    summary = {
        "NEW_PRODUCTION_RUNS_CHECKED": len(results),
        "WITH_INFERENCE_RUN": len(linked),
        "PRODUCTION_KIND": len(prod),
        "NEW_PRODUCTION_ASSESSMENTS_WITH_INFERENCE_RUN_PCT": round(
            100.0 * len(linked) / max(1, len(results)), 1
        ),
        "OPPORTUNITY_MUTATIONS": sum(
            1 for r in results if r.get("opportunities_unchanged") is False
        ),
        "results": results,
    }
    print("SUMMARY=" + json.dumps(summary, ensure_ascii=False, default=str), flush=True)
    Path("/tmp/phase6b_controlled_prod.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    ok = (
        len(linked) >= 10
        and len(prod) == len(linked)
        and summary["OPPORTUNITY_MUTATIONS"] == 0
        and summary["NEW_PRODUCTION_ASSESSMENTS_WITH_INFERENCE_RUN_PCT"] == 100.0
    )
    print("CONTROLLED_PROD=" + ("PASS" if ok else "FAIL"), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
