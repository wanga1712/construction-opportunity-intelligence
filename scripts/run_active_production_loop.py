"""ACTIVE_NEED_HTTP_AND_PROMOTION_V1: catch-up + continuous production loop.

Phase 1 (catch-up): process the A-bucket of NEEDED_BUT_LOCAL_MISSING_V2
  (download -> parse_file_with_meta -> extract_and_persist), then promote
  (confirmed_base -> current_effective -> medals) through existing tools.

Phase 2 (continuous): the service never terminates. Each cycle refreshes the
  plan with newly-active procurements (from routing-owned state that production
  source-sync/admission already maintains), downloads only needed documents,
  extracts, promotes and recalculates. No new classifier is introduced.

No positive signal -> no opportunity is created here (routing owns that).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, "/opt/tender_documents_research")
sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

PLAN_VERSION = "NEEDED_BUT_LOCAL_MISSING_V2"
A_BUCKETS = ("A_OPEN_CURRENT", "A_AWARDED_OBJECT")
PARSEABLE = "('docx','pdf','xlsx','xlsm','doc','xls')"
HEARTBEAT = "/tmp/active_production_loop.json"
STEPS_LOG = "/tmp/active_production_steps.log"
CRM_DIR = "/opt/CRM_Streamlit"
WAVE = "/opt/CRM_Streamlit/scripts/run_wave2a_http.py"
PROMOTE_CONFIRMED = "/opt/CRM_Streamlit/scripts/write_confirmed_base.py"
PROMOTE_MEDALS = "/opt/CRM_Streamlit/scripts/run_v3_daily_medal_reevaluation.py"
CYCLE_SLEEP_SECONDS = int(os.getenv("ACTIVE_LOOP_SLEEP_SECONDS", "900"))


def di_connect():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def crm_connect():
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    return psycopg2.connect(**require_crm_db_connect_kwargs())


def active_bucket_by_procurement(crm):
    """bucket(procurement) from routing-owned lifecycle/opportunity state."""
    buckets = {}
    cur = crm.cursor()
    cur.execute(
        """SELECT sa.procurement_id, sa.source_lifecycle,
                  coalesce(o.any_object, false), coalesce(o.any_followup, false)
             FROM crm_procurement_scope_authority sa
             LEFT JOIN (
               SELECT procurement_id,
                      bool_or(opportunity_track IN
                        ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT','DESIGN_INFLUENCE')) AS any_object,
                      bool_or(commercial_state = 'FOLLOW_UP_AWARDED') AS any_followup
                 FROM crm_procurement_category_opportunities
                WHERE status = 'CURRENT'
                GROUP BY 1) o ON o.procurement_id = sa.procurement_id""",
    )
    for pid, life, any_object, any_followup in cur.fetchall():
        if life == "OPEN":
            buckets[int(pid)] = "A_OPEN_CURRENT"
        elif life == "AWARDED" and (any_object or any_followup):
            buckets[int(pid)] = "A_AWARDED_OBJECT"
        else:
            buckets[int(pid)] = "NOT_ACTIVE"
    cur.close()
    return buckets


def _flag(name, *needles):
    low = (name or "").lower()
    return any(n in low for n in needles)


def refresh_plan(di, crm):
    """Grow the immutable plan with newly-active procurements (idempotent)."""
    buckets = active_bucket_by_procurement(crm)
    active = [pid for pid, b in buckets.items() if b in A_BUCKETS]
    if not active:
        return 0
    cur = di.cursor()
    cur.execute(
        "SELECT coalesce(physical_download_key,'') FROM document_files"
        " WHERE local_path IS NOT NULL AND local_deleted_at IS NULL AND download_status='COMPLETED'"
    )
    present_keys = {r[0] for r in cur.fetchall() if r[0]}
    added = 0
    for start in range(0, len(active), 3000):
        chunk = active[start:start + 3000]
        cur.execute(
            f"""WITH cand AS (
                  SELECT df.id, df.procurement_id, df.url, df.file_name, df.file_size_bytes,
                         lower(coalesce(substring(df.file_name from '\\.([A-Za-z0-9]+)$'),'?')) AS ext,
                         nullif(df.physical_download_key,'') AS pkey
                    FROM document_files df
                   WHERE df.procurement_id = ANY(%s)
                     AND (df.local_path IS NULL OR df.local_deleted_at IS NOT NULL)
                     AND lower(coalesce(substring(df.file_name from '\\.([A-Za-z0-9]+)$'),'?')) IN {PARSEABLE}
                     AND coalesce(df.file_name,'') NOT LIKE '~$%%'
                     AND coalesce(df.error_message,'') !~* '(CORRUPT|INVALID_FILE|PACKAGE_NOT_FOUND|UNSUPPORTED_ZIP)'
                     AND df.id NOT IN (SELECT source_document_id FROM document_extraction_outcomes
                                        WHERE extractor_version='EMBEDDED_EXTRACTOR_V1')
                )
                SELECT DISTINCT ON (coalesce(pkey,'id:'||id))
                       id, procurement_id, url, file_name, file_size_bytes, ext, pkey
                  FROM cand ORDER BY coalesce(pkey,'id:'||id), id""",
            (chunk,),
        )
        ins = []
        for (sid, pid, url, fname, size, ext, pkey) in cur.fetchall():
            if pkey and pkey in present_keys:
                continue
            bucket = buckets.get(int(pid))
            if bucket not in A_BUCKETS:
                continue
            is_est = _flag(fname, "смет", "нмцк")
            is_tz = _flag(fname, "тех", "тз", "специфик", "ооз", "описание объекта")
            prio = "P0" if (ext in ("xlsx", "xls", "xlsm") or is_est or is_tz) else "P1"
            cls = "ESTIMATE" if is_est else ("TECH_SPEC" if is_tz else "OTHER")
            ins.append((PLAN_VERSION, sid, pid, pkey, prio, ext, cls, size,
                        "auto_cycle", url, bucket))
        if ins:
            execute_values(
                cur,
                """INSERT INTO needed_local_missing_v2_plan
                     (plan_version, source_document_id, procurement_id, physical_download_key,
                      priority, extension, document_class, file_size_bytes, selection_reason,
                      url, lifecycle_bucket)
                   VALUES %s ON CONFLICT (plan_version, source_document_id) DO NOTHING""",
                ins, page_size=1000,
            )
        di.commit()
    cur.close()
    return added


def run_step(cmd):
    with open(STEPS_LOG, "a", encoding="utf-8") as fh:
        fh.write("\n### %s :: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(cmd)))
        fh.flush()
        subprocess.run(cmd, cwd=CRM_DIR, stdout=fh, stderr=subprocess.STDOUT, check=False)


def heartbeat(payload):
    try:
        with open(HEARTBEAT, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    only_once = "--once" in sys.argv
    cycle = 0
    while True:
        cycle += 1
        di = di_connect()
        crm = crm_connect()
        try:
            refresh_plan(di, crm)
            cur = di.cursor()
            cur.execute(
                """SELECT count(*) FILTER (WHERE status IN ('PLANNED','DOWNLOADED')) AS open_a,
                          count(*) FILTER (WHERE status='PROCESSED') AS done_a
                     FROM needed_local_missing_v2_plan
                    WHERE plan_version=%s AND lifecycle_bucket = ANY(%s)""",
                (PLAN_VERSION, list(A_BUCKETS)),
            )
            open_a, done_a = cur.fetchone()
        finally:
            crm.close()
            di.close()

        run_step([sys.executable, WAVE])
        run_step([sys.executable, PROMOTE_CONFIRMED, "--write"])
        run_step([sys.executable, PROMOTE_MEDALS, "--apply"])

        heartbeat({
            "cycle": cycle,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "A_open": int(open_a or 0),
            "A_processed": int(done_a or 0),
            "sleep_seconds": CYCLE_SLEEP_SECONDS,
        })
        if only_once:
            return 0
        time.sleep(CYCLE_SLEEP_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
