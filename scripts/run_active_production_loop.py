"""ACTIVE_NEED_HTTP_AND_PROMOTION_V1: catch-up + continuous production loop.

Each cycle:
  1. refresh the immutable plan with newly-active procurements
     (A_OPEN_CURRENT = OPEN + CURRENT opportunity;
      A_AWARDED_OBJECT = AWARDED + object/project/embedded signal);
  2. process ONE batch of eligible A documents (download -> parse -> extract);
  3. promote (confirmed_base) and recalculate (current_effective + medals);
  4. next batch immediately while backlog remains, else sleep ~15 min.

No new classifier is introduced and no opportunity is created here: routing owns
that. B_DISCOVERY / C_* buckets are never taken by HTTP.
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
from src.services.commercial_routing_v3.document_classifier_v1 import (  # noqa: E402
    DocumentClass,
    classify_document_metadata,
)

PLAN_VERSION = "NEEDED_BUT_LOCAL_MISSING_V2"
A_BUCKETS = ("A_OPEN_CURRENT", "A_AWARDED_OBJECT")
PARSEABLE = "('docx','pdf','xlsx','xlsm','doc','xls')"
#: Only these document classes carry material/characteristic evidence for the
#: embedded normalizer. Legal/participant/contract boilerplate is never fetched.
MATERIAL_DOC_CLASSES = frozenset({
    DocumentClass.ESTIMATE.value,
    DocumentClass.BOQ.value,
    DocumentClass.TECH_SPEC.value,
    DocumentClass.PRODUCT_SPECIFICATION.value,
    DocumentClass.MATERIAL_SPECIFICATION.value,
    DocumentClass.NMCK_JUSTIFICATION.value,
    DocumentClass.PROJECT_DOCUMENTATION.value,
    DocumentClass.WORKING_DOCUMENTATION.value,
})
P0_DOC_CLASSES = frozenset({
    DocumentClass.ESTIMATE.value,
    DocumentClass.BOQ.value,
    DocumentClass.TECH_SPEC.value,
    DocumentClass.PRODUCT_SPECIFICATION.value,
    DocumentClass.MATERIAL_SPECIFICATION.value,
    DocumentClass.NMCK_JUSTIFICATION.value,
})
HEARTBEAT = "/tmp/active_production_loop.json"
STEPS_LOG = "/tmp/active_production_steps.log"
CRM_DIR = "/opt/CRM_Streamlit"
WAVE = "/opt/CRM_Streamlit/scripts/run_wave2a_http.py"
VERIFY_DIRECT = "/opt/CRM_Streamlit/scripts/verify_direct_supply_facts.py"
PROMOTE_FACTS = "/opt/CRM_Streamlit/scripts/build_confirmed_facts.py"
PROMOTE_CONFIRMED = "/opt/CRM_Streamlit/scripts/write_confirmed_base.py"
PROMOTE_MEDALS = "/opt/CRM_Streamlit/scripts/run_v3_daily_medal_reevaluation.py"
CYCLE_SLEEP_SECONDS = int(os.getenv("ACTIVE_LOOP_SLEEP_SECONDS", "900"))
BATCH_LIMIT = int(os.getenv("ACTIVE_LOOP_BATCH", "100"))
MEDAL_LIMIT = int(os.getenv("ACTIVE_LOOP_MEDAL_LIMIT", "50000"))


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
    """bucket(procurement) from routing-owned lifecycle/opportunity state.

    A_OPEN_CURRENT requires a CURRENT opportunity; OPEN without one is discovery
    (never downloaded by the loop).
    """
    buckets = {}
    cur = crm.cursor()
    cur.execute(
        """SELECT sa.procurement_id, sa.source_lifecycle,
                  (o.procurement_id IS NOT NULL) AS has_current,
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
    for pid, life, has_current, any_object, any_followup in cur.fetchall():
        if life == "OPEN" and has_current:
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


def current_categories_by_procurement(crm):
    cats = {}
    cur = crm.cursor()
    cur.execute(
        "SELECT procurement_id, commercial_category_code"
        "  FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
    )
    for pid, cat in cur.fetchall():
        cats.setdefault(int(pid), []).append(str(cat))
    cur.close()
    return cats


def refresh_plan(di, crm):
    """Grow the immutable plan with newly-active procurements (idempotent)."""
    buckets = active_bucket_by_procurement(crm)
    cats_by_proc = current_categories_by_procurement(crm)
    active = [pid for pid, b in buckets.items() if b in A_BUCKETS]
    if not active:
        return 0
    cur = di.cursor()
    cur.execute(
        "SELECT coalesce(physical_download_key,'') FROM document_files"
        " WHERE local_path IS NOT NULL AND local_deleted_at IS NULL AND download_status='COMPLETED'"
    )
    present_keys = {r[0] for r in cur.fetchall() if r[0]}
    # version+category scoped outcome memory: (source_document_id, category_code)
    cur.execute(
        "SELECT source_document_id, coalesce(category_code,'') FROM document_extraction_outcomes"
        " WHERE extractor_version='EMBEDDED_EXTRACTOR_V1'"
    )
    done_pairs = {(int(r[0]), str(r[1])) for r in cur.fetchall()}
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
            # already-processed check is version+category scoped
            cats = cats_by_proc.get(int(pid)) or [""]
            if all((int(sid), c) in done_pairs for c in cats):
                continue
            cls = classify_document_metadata(fname).document_class.value
            if cls not in MATERIAL_DOC_CLASSES:
                continue
            prio = "P0" if (ext in ("xlsx", "xls", "xlsm") or cls in P0_DOC_CLASSES) else "P1"
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
            added += max(0, cur.rowcount or 0)
        di.commit()
    # Self-heal previously-planned backlog: reclassify by file name and drop the
    # non-material classes so wave2a never downloads them.
    cur.execute(
        """SELECT p.id, df.file_name
             FROM needed_local_missing_v2_plan p
             JOIN document_files df ON df.id = p.source_document_id
            WHERE p.plan_version=%s AND p.status IN ('PLANNED','DOWNLOADED')
              AND (p.document_class IS NULL OR NOT (p.document_class = ANY(%s)))""",
        (PLAN_VERSION, list(MATERIAL_DOC_CLASSES)),
    )
    for row_id, fname in cur.fetchall():
        cls = classify_document_metadata(fname).document_class.value
        if cls in MATERIAL_DOC_CLASSES:
            prio = "P0" if cls in P0_DOC_CLASSES else "P1"
            cur.execute(
                "UPDATE needed_local_missing_v2_plan"
                " SET document_class=%s, priority=%s, updated_at=now() WHERE id=%s",
                (cls, prio, row_id),
            )
        else:
            cur.execute(
                "UPDATE needed_local_missing_v2_plan"
                " SET status='FAILED', error_message='excluded_non_material', updated_at=now()"
                " WHERE id=%s",
                (row_id,),
            )
    di.commit()
    cur.close()
    return added


def run_step(cmd):
    """Run one pipeline step; return its exit code (never silently ignored)."""
    with open(STEPS_LOG, "a", encoding="utf-8") as fh:
        fh.write("\n### %s :: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(cmd)))
        fh.flush()
        rc = subprocess.run(cmd, cwd=CRM_DIR, stdout=fh, stderr=subprocess.STDOUT).returncode
        fh.write("### rc=%d\n" % rc)
    return rc


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
            added = refresh_plan(di, crm)
            cur = di.cursor()
            cur.execute(
                """SELECT count(*) FILTER (WHERE status IN ('PLANNED','DOWNLOADED')) AS open_a,
                          count(*) FILTER (WHERE status='PROCESSED') AS done_a,
                          count(*) FILTER (WHERE status='FAILED') AS failed_a
                     FROM needed_local_missing_v2_plan
                    WHERE plan_version=%s AND lifecycle_bucket = ANY(%s)""",
                (PLAN_VERSION, list(A_BUCKETS)),
            )
            open_a, done_a, failed_a = cur.fetchone()
        finally:
            crm.close()
            di.close()

        if open_a and int(open_a) > 0:
            state = "BATCH_DONE"
            sleep_for = 0
            rc = []
            # Fail-closed: a failed step stops the chain; the next iteration retries.
            rc_wave = run_step([sys.executable, WAVE, "--limit", str(BATCH_LIMIT)])
            rc.append(rc_wave)
            if rc_wave == 0:
                # Direct-supply documentary verification (quote present in snapshot).
                rc_verify = run_step([sys.executable, VERIFY_DIRECT, "--apply"])
                rc.append(rc_verify)
                if rc_verify == 0:
                    rc_facts = run_step([sys.executable, PROMOTE_FACTS])
                    rc.append(rc_facts)
                    if rc_facts == 0:
                        rc_conf = run_step([sys.executable, PROMOTE_CONFIRMED, "--write"])
                        rc.append(rc_conf)
                        if rc_conf == 0:
                            rc_medal = run_step([sys.executable, PROMOTE_MEDALS,
                                                 "--apply", "--limit", str(MEDAL_LIMIT)])
                            rc.append(rc_medal)
            if any(code != 0 for code in rc):
                state = "STEP_FAILED"
                sleep_for = 60
        else:
            state = "WAITING"
            rc = []
            sleep_for = CYCLE_SLEEP_SECONDS

        heartbeat({
            "cycle": cycle,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "state": state,
            "plan_rows_added": added,
            "batch_limit": BATCH_LIMIT,
            "A_open": int(open_a or 0),
            "A_processed": int(done_a or 0),
            "A_failed": int(failed_a or 0),
            "step_rc": rc,
            "sleep_seconds": sleep_for,
        })
        if only_once:
            return 0
        if sleep_for:
            time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
