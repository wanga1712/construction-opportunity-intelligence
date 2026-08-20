#!/usr/bin/env python3
"""Phase 6A controlled SHADOW smoke (5 cases). Does not mutate production assessments."""
from __future__ import annotations

import json
import os
import sys
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


SMOKE_IDS = [840, 1, 8003, 21782, 13248]  # road prior, lighting-ish, road prior, recent, golden


def _load_procurement(crm_db, pid: int) -> dict | None:
    rows = crm_db.execute_query(
        "SELECT * FROM crm_procurements WHERE id = %s",
        (pid,),
    )
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


def _torgi_visible(crm_db) -> int:
    """Stable visibility fingerprint for smoke (publication filters when available)."""
    try:
        from src.services.torgi_publication import torgi_publication_sql_filters

        frag = torgi_publication_sql_filters()
        q = f"""
            SELECT count(*)
            FROM crm_procurements cp
            WHERE COALESCE(cp.crm_stage, '') = 'torgi'
              AND COALESCE(cp.award_status, '') = 'submission_open'
            {frag}
        """
        return int(crm_db.execute_scalar(q) or 0)
    except Exception as exc:
        print("torgi_publication_filter_error", type(exc).__name__, str(exc)[:200])
        # Fallback: stage/status only — still detects accidental bulk stage flips.
        try:
            return int(
                crm_db.execute_scalar(
                    """
                    SELECT count(*)
                    FROM crm_procurements cp
                    WHERE COALESCE(cp.crm_stage, '') = 'torgi'
                      AND COALESCE(cp.award_status, '') = 'submission_open'
                    """
                )
                or 0
            )
        except Exception as exc2:
            print("torgi_count_error", exc2)
            return -1


def main() -> int:
    _, _, crm_db, _ = connect_databases()
    torgi_before = _torgi_visible(crm_db)
    results = []

    for pid in SMOKE_IDS:
        row = _load_procurement(crm_db, pid)
        if not row:
            results.append({"procurement_id": pid, "error": "NOT_FOUND"})
            continue
        a_before = _assessment_fingerprint(crm_db, pid)
        o_before = _opp_count(crm_db, pid)

        # Build best-effort procurement dict for prompt.
        try:
            mi = ensure_v3_model_input(row, crm_db)
            procurement = model_input_as_prompt_procurement(mi)
            procurement["routing_lane"] = row.get("routing_lane")
            procurement["commercial_lane"] = row.get("commercial_lane")
        except Exception as exc:
            print("model_input_fallback", pid, exc)
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
            compute_business_preview=True,
        )

        a_after = _assessment_fingerprint(crm_db, pid)
        o_after = _opp_count(crm_db, pid)
        results.append(
            {
                "procurement_id": pid,
                "title": (row.get("auction_name") or "")[:80],
                "inference_run_id": out.get("inference_run_id"),
                "parse_status": out.get("parse_status"),
                "validation_status": out.get("validation_status"),
                "raw_sha": out.get("raw_model_sha256"),
                "validated_sha": out.get("validated_model_sha256"),
                "assessment_unchanged": a_before == a_after,
                "opportunities_unchanged": o_before == o_after,
                "assessment_before": a_before,
                "assessment_after": a_after,
                "opp_before": o_before,
                "opp_after": o_after,
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False))

    torgi_after = _torgi_visible(crm_db)
    summary = {
        "cases": len(results),
        "raw_capture_success": sum(1 for r in results if r.get("raw_sha")),
        "validation_success": sum(
            1 for r in results if r.get("validation_status") == "VALIDATED_SUCCESS"
        ),
        "assessment_mutations": sum(
            1 for r in results if r.get("assessment_unchanged") is False
        ),
        "opportunity_mutations": sum(
            1 for r in results if r.get("opportunities_unchanged") is False
        ),
        "torgi_before": torgi_before,
        "torgi_after": torgi_after,
        "torgi_unchanged": torgi_before == torgi_after,
        "results": results,
    }
    print("SUMMARY=" + json.dumps(summary, ensure_ascii=False))
    ok = (
        summary["raw_capture_success"] == len([r for r in results if "error" not in r])
        and summary["assessment_mutations"] == 0
        and summary["opportunity_mutations"] == 0
        and summary["torgi_unchanged"]
    )
    print("SHADOW_SMOKE=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
