#!/usr/bin/env python3
"""Phase 6A golden SHADOW corpus (67 frozen cases). No production assessment writes."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
ROOT = Path("/opt/CRM_Streamlit") if Path("/opt/CRM_Streamlit").is_dir() else _HERE.parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.crm_ai_assessment_runner import ensure_v3_model_input
from src.services.commercial_routing_v3.model_input import model_input_as_prompt_procurement
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference

def _load_golden_ids() -> list[int]:
    candidates = [
        ROOT / "docs" / "reports" / "crm_v3_model_authority_restoration" / "GOLDEN_BAD_CASE_SNAPSHOT.json",
        Path("/tmp") / "GOLDEN_BAD_CASE_SNAPSHOT.json",
    ]
    for p in candidates:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            ids = [int(c["procurement_id"]) for c in data["cases"]]
            assert len(ids) == 67, f"expected 67, got {len(ids)} from {p}"
            return ids
    raise FileNotFoundError("GOLDEN_BAD_CASE_SNAPSHOT.json not found")


def _load_procurement(crm_db, pid: int) -> dict | None:
    rows = crm_db.execute_query("SELECT * FROM crm_procurements WHERE id = %s", (pid,))
    return dict(rows[0]) if rows else None


def _assessment_fingerprint(crm_db, pid: int) -> tuple:
    rows = crm_db.execute_query(
        """
        SELECT id, assessment_version, status,
               md5(coalesce(normalized_result::text,'')) AS nr_md5
        FROM procurement_ai_assessments
        WHERE procurement_id = %s AND is_current = TRUE
        LIMIT 1
        """,
        (pid,),
    )
    if not rows:
        return (None, None, None, None)
    r = rows[0]
    return (r.get("id"), r.get("assessment_version"), r.get("status"), r.get("nr_md5"))


def _opp_count(crm_db, pid: int) -> int:
    try:
        return int(
            crm_db.execute_scalar(
                """
                SELECT count(*) FROM crm_procurement_category_opportunities
                WHERE procurement_id = %s AND status = 'CURRENT'
                """,
                (pid,),
            )
            or 0
        )
    except Exception:
        return -1


def main() -> int:
    ids = _load_golden_ids()
    _, _, crm_db, _ = connect_databases()
    results = []
    t0 = time.time()

    for i, pid in enumerate(ids, 1):
        row = _load_procurement(crm_db, pid)
        if not row:
            results.append({"procurement_id": pid, "error": "NOT_FOUND"})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
            continue
        a_before = _assessment_fingerprint(crm_db, pid)
        o_before = _opp_count(crm_db, pid)
        try:
            mi = ensure_v3_model_input(row, crm_db)
            procurement = model_input_as_prompt_procurement(mi)
        except Exception as exc:
            print(f"model_input_fallback {pid} {exc}", flush=True)
            mi = None
            procurement = {
                "title": row.get("auction_name"),
                "okpd_code": row.get("okpd_code"),
                "okpd_name": row.get("okpd_name"),
                "price": float(row.get("initial_price") or 0),
                "region": row.get("delivery_region"),
                "customer": row.get("customer"),
                "source_table": row.get("source_table"),
            }

        out = run_shadow_inference(
            crm_db,
            procurement_id=pid,
            procurement=procurement,
            model_input=mi if isinstance(mi, dict) else None,
            acquire_gpu=True,
            dry_run_persist=False,
            compute_business_preview=False,
        )
        a_after = _assessment_fingerprint(crm_db, pid)
        o_after = _opp_count(crm_db, pid)
        rec = {
            "i": i,
            "procurement_id": pid,
            "inference_run_id": out.get("inference_run_id"),
            "parse_status": out.get("parse_status"),
            "validation_status": out.get("validation_status"),
            "raw_sha": out.get("raw_model_sha256"),
            "validated_sha": out.get("validated_model_sha256"),
            "assessment_unchanged": a_before == a_after,
            "opportunities_unchanged": o_before == o_after,
        }
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

    summary = {
        "GOLDEN_SHADOW_RUNS": len(results),
        "RAW_CAPTURE_SUCCESS": sum(1 for r in results if r.get("raw_sha")),
        "PARSE_SUCCESS": sum(1 for r in results if r.get("parse_status") == "PARSED_OK"),
        "PARSE_FAILURE": sum(
            1 for r in results if r.get("parse_status") == "RAW_RECEIVED_PARSE_FAILED"
        ),
        "VALIDATION_SUCCESS": sum(
            1 for r in results if r.get("validation_status") == "VALIDATED_SUCCESS"
        ),
        "VALIDATION_FAILURE": sum(
            1 for r in results if r.get("validation_status") == "PARSED_SCHEMA_INVALID"
        ),
        "MODEL_CALL_FAILED": sum(
            1 for r in results if r.get("parse_status") == "MODEL_CALL_FAILED"
        ),
        "NOT_FOUND": sum(1 for r in results if r.get("error") == "NOT_FOUND"),
        "PRODUCTION_ASSESSMENTS_MUTATED": sum(
            1 for r in results if r.get("assessment_unchanged") is False
        ),
        "PRODUCTION_OPPORTUNITIES_MUTATED": sum(
            1 for r in results if r.get("opportunities_unchanged") is False
        ),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    print("SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)
    ok = (
        summary["GOLDEN_SHADOW_RUNS"] == 67
        and summary["PRODUCTION_ASSESSMENTS_MUTATED"] == 0
        and summary["PRODUCTION_OPPORTUNITIES_MUTATED"] == 0
        and summary["NOT_FOUND"] == 0
        and summary["RAW_CAPTURE_SUCCESS"] == 67
    )
    print("GOLDEN_SHADOW=" + ("PASS" if ok else "FAIL"), flush=True)
    out_path = Path("/tmp/phase6a_golden_shadow_summary.json")
    out_path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE={out_path}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
