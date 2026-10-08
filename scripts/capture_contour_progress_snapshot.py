#!/usr/bin/env python3
"""Capture one ANALYTICAL CONTOUR progress snapshot into crm.

WIP: PHYSICAL S13 PROGRESS SNAPSHOTS + 24H DELTA. Measurement only.

Runs on S13 (systemd timer, every 15 min). It performs the heavy aggregation
once and appends a compact row so the physical dashboard only reads the latest
snapshot. No routing/drain/queue/medal/classification changes.

Progress is taken from the canonical pass-1 telemetry
(``collect_pass1_telemetry``) so TOTAL/PROCESSED/REMAINING match the initial-pass
runner exactly. Honest-only fields: anything not derivable is left NULL.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.environ.get(
    "CRM_REPO_ROOT",
    "/opt/CRM_Streamlit" if os.path.isdir("/opt/CRM_Streamlit")
    else os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO_ROOT, ".env"))

from src.services.system_health_pass1 import (  # noqa: E402
    ADMISSION_POLICY,
    collect_pass1_telemetry,
)
from src.infrastructure.crm_connection import connect_crm  # noqa: E402


def _rows(cur, sql, params=None):
    cur.execute(sql, params or ())
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _scalar(cur, sql, params=None):
    cur.execute(sql, params or ())
    row = cur.fetchone()
    return row[0] if row else None


def compute_pass_split(cur):
    """deterministic vs qwen split of the eligible done cohort (honest)."""
    done = _scalar(cur, """
        SELECT count(DISTINCT cp.id)
        FROM crm_procurements cp
        JOIN crm_procurement_scope_authority a ON a.procurement_id = cp.id
        WHERE a.admission_state = 'ELIGIBLE' AND a.admission_policy_version = %s
          AND cp.ai_assessment_status IN ('COMPLETED', 'NEEDS_REVIEW')
    """, (ADMISSION_POLICY,)) or 0
    qwen = _scalar(cur, """
        SELECT count(DISTINCT cp.id)
        FROM crm_procurements cp
        JOIN crm_procurement_scope_authority a ON a.procurement_id = cp.id
        JOIN procurement_ai_assessments pa
             ON pa.procurement_id = cp.id AND pa.is_current
        WHERE a.admission_state = 'ELIGIBLE' AND a.admission_policy_version = %s
          AND cp.ai_assessment_status IN ('COMPLETED', 'NEEDS_REVIEW')
          AND pa.model_version ILIKE 'qwen%%'
    """, (ADMISSION_POLICY,)) or 0
    return int(done), int(qwen), int(max(0, done - qwen))


def compute_medals(cur):
    out = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0}
    for r in _rows(cur, """
        SELECT upper(coalesce(current_effective_medal,'')) AS m,
               count(DISTINCT procurement_id) AS n
        FROM crm_procurement_category_opportunities
        WHERE status = 'CURRENT'
        GROUP BY 1
    """):
        if r["m"] in out:
            out[r["m"]] = int(r["n"])
    return out


def document_counts():
    """Document queue counts from document_intelligence (read-only)."""
    sql = (
        "SELECT "
        "count(1) FILTER (WHERE status IN ('PENDING','PRE_RESEARCH_WAITING')), "
        "count(1) FILTER (WHERE status = 'PROCESSING'), "
        "count(1) FILTER (WHERE status = 'COMPLETED'), "
        "count(1) FILTER (WHERE status = 'NO_LINKS'), "
        "count(1) FILTER (WHERE status = 'FAILED') "
        "FROM document_processing_queue"
    )
    try:
        proc = subprocess.run(
            ["sudo", "-n", "-u", "postgres", "psql", "-d", "document_intelligence",
             "-At", "-F", "|", "-c", sql],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0 or "|" not in proc.stdout:
            return {}
        parts = proc.stdout.strip().split("|")
        if len(parts) != 5:
            return {}
        return {
            "document_pending": int(parts[0]),
            "document_processing": int(parts[1]),
            "document_completed_total": int(parts[2]),
            "document_no_links": int(parts[3]),
            "document_failed": int(parts[4]),
        }
    except Exception:
        return {}


INSERT_PROGRESS = """
INSERT INTO crm_contour_progress_snapshots (
    eligible_total, processed_total, remaining_total, in_progress,
    deterministic_accept, no_commercial_entry, qwen_processed, classified_total,
    backlog_drain_remaining,
    gold, silver, bronze, wood, failed, blocked,
    document_pending, document_processing, document_completed_total,
    document_no_links, document_failed
) VALUES (
    %(eligible_total)s, %(processed_total)s, %(remaining_total)s, %(in_progress)s,
    %(deterministic_accept)s, %(no_commercial_entry)s, %(qwen_processed)s, %(classified_total)s,
    %(backlog_drain_remaining)s,
    %(gold)s, %(silver)s, %(bronze)s, %(wood)s, %(failed)s, %(blocked)s,
    %(document_pending)s, %(document_processing)s, %(document_completed_total)s,
    %(document_no_links)s, %(document_failed)s
) RETURNING id, captured_at
"""

INSERT_CATEGORY = """
INSERT INTO crm_contour_category_snapshots (
    captured_at, category_code, total, classified, unclassified, coverage_pct
) VALUES (NOW(), %(category_code)s, %(total)s, %(classified)s, %(unclassified)s, %(coverage_pct)s)
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--print-only", action="store_true",
                    help="Compute and print the payload without writing.")
    args = ap.parse_args(argv)

    tel = collect_pass1_telemetry()
    if not tel.get("available"):
        print(f"SNAPSHOT=FAIL telemetry_error={tel.get('error')}")
        return 1

    conn = connect_crm()
    cur = conn.cursor()

    done_total, qwen, deterministic = compute_pass_split(cur)
    medals = compute_medals(cur)
    docs = document_counts()

    done = int(tel.get("done") or 0)
    running = int(tel.get("running") or 0)
    workset = int(tel.get("workset") or 0)
    backlog = int(tel.get("remaining") or 0)
    remaining = max(0, workset - done)

    payload = {
        "eligible_total": workset,
        "processed_total": done,
        "remaining_total": remaining,
        "in_progress": running,
        "deterministic_accept": deterministic,
        "no_commercial_entry": int(tel.get("no_commercial_entry") or 0),
        "qwen_processed": qwen,
        "classified_total": int(tel.get("classified") or 0),
        "backlog_drain_remaining": backlog,
        "gold": medals["GOLD"], "silver": medals["SILVER"],
        "bronze": medals["BRONZE"], "wood": medals["WOOD"],
        "failed": int(tel.get("failed_terminal") or 0),
        "blocked": int(tel.get("needs_review") or 0),
        "document_pending": docs.get("document_pending"),
        "document_processing": docs.get("document_processing"),
        "document_completed_total": docs.get("document_completed_total"),
        "document_no_links": docs.get("document_no_links"),
        "document_failed": docs.get("document_failed"),
    }

    if args.print_only:
        import json
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        cur.close(); conn.close()
        return 0

    cur.execute(INSERT_PROGRESS, payload)
    snap_id, captured_at = cur.fetchone()
    for c in tel.get("categories") or []:
        total = int(c.get("total") or 0)
        resolved = int(c.get("resolved") or 0)
        if total <= 0:
            continue
        cur.execute(INSERT_CATEGORY, {
            "category_code": c.get("category"),
            "total": total,
            "classified": resolved,
            "unclassified": int(c.get("unclassified") or 0),
            "coverage_pct": c.get("coverage_pct"),
        })
    conn.commit()
    cur.close(); conn.close()
    print(f"SNAPSHOT=PASS id={snap_id} captured_at={captured_at} "
          f"total={workset} processed={done} remaining={remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
