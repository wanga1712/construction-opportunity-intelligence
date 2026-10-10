"""Batch run of the DIRECT contour: extraction + TKP file per procurement (read-only)."""
import json
import os
import sys
import time

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.db_bootstrap import connect_databases
from src.services.direct_document_extractor import build_tkp_request, load_direct_extraction
from src.services.procurement_card_dossier_service import load_procurement_dossier

LIMIT = int(os.getenv("DIRECT_BATCH_LIMIT", "10"))
OFFSET = int(os.getenv("DIRECT_BATCH_OFFSET", "0"))
OUTDIR = os.getenv("DIRECT_BATCH_OUTDIR", "/tmp/tkp")
VERBOSE = os.getenv("DIRECT_BATCH_VERBOSE", "0") == "1"


def candidate_pids():
    kw = dict(require_crm_db_connect_kwargs())
    crm = psycopg2.connect(**kw)
    try:
        with crm.cursor() as cur:
            cur.execute(
                """
                SELECT procurement_id FROM crm_procurement_category_opportunities
                WHERE upper(coalesce(opportunity_track, '')) = 'DIRECT_SUPPLY'
                GROUP BY procurement_id
                ORDER BY procurement_id DESC
                """
            )
            pids = [r[0] for r in cur.fetchall()]
    finally:
        crm.close()
    di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
    try:
        with di.cursor() as cur:
            cur.execute(
                """SELECT procurement_id FROM document_files
                   WHERE download_status = 'COMPLETED' AND local_path IS NOT NULL
                     AND procurement_id = ANY(%s)""",
                (pids,),
            )
            have_docs = {r[0] for r in cur.fetchall()}
    finally:
        di.close()
    return [p for p in pids if p in have_docs]


def main() -> int:
    os.makedirs(OUTDIR, exist_ok=True)
    all_pids = candidate_pids()
    pids = all_pids[OFFSET:OFFSET + LIMIT]
    print("batch candidates=%d selected=%d offset=%d limit=%d outdir=%s" % (
        len(all_pids), len(pids), OFFSET, LIMIT, OUTDIR), flush=True)
    _radar, _tender, crm_db, warn = connect_databases()
    if crm_db is None:
        print("crm_db=None warn=%s -> abort" % warn)
        return 2
    summary = []
    for pid in pids:
        started = time.time()
        try:
            ext = load_direct_extraction(pid)
            dossier = load_procurement_dossier(crm_db, pid)
            tkp = build_tkp_request(ext, dossier)
            path = os.path.join(OUTDIR, "tkp_%s.txt" % pid)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(tkp)
            secs = sum(len(v or []) for v in (ext.get("sections") or {}).values())
            row = {
                "pid": pid,
                "number": (dossier.get("identity") or {}).get("contract_number"),
                "docs": ext.get("files"),
                "spec": len(ext.get("spec") or []),
                "tech": len(ext.get("tech") or []),
                "req": len(ext.get("requirements") or []),
                "sections": secs,
                "tkp_chars": len(tkp),
                "sec": round(time.time() - started, 1),
            }
        except Exception as exc:  # noqa: BLE001
            row = {"pid": pid, "error": "%s: %s" % (type(exc).__name__, exc)}
        summary.append(row)
        if VERBOSE or "error" in row or not row.get("spec"):
            print(json.dumps(row, ensure_ascii=False), flush=True)
    ok = sum(1 for r in summary if "error" not in r and r.get("tkp_chars"))
    with_spec = sum(1 for r in summary if r.get("spec"))
    with_tech = sum(1 for r in summary if r.get("tech"))
    with_any = sum(1 for r in summary if (r.get("spec") or r.get("tech") or r.get("sections")))
    print("batch done: ok=%d/%d with_spec=%d with_tech=%d with_any=%d" % (
        ok, len(summary), with_spec, with_tech, with_any))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
