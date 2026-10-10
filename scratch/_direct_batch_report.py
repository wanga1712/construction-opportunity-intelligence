"""Full DIRECT pool pass: per-pid extraction coverage + JSONL dump (read-only)."""
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

JSONL = os.getenv("DIRECT_REPORT_JSONL", "/tmp/direct_batch.jsonl")


def direct_pids():
    kw = dict(require_crm_db_connect_kwargs())
    crm = psycopg2.connect(**kw)
    try:
        with crm.cursor() as cur:
            cur.execute(
                """SELECT procurement_id FROM crm_procurement_category_opportunities
                   WHERE upper(coalesce(opportunity_track,''))='DIRECT_SUPPLY'
                   GROUP BY procurement_id ORDER BY procurement_id DESC"""
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        crm.close()


def files_map(pids):
    kw = dict(require_crm_db_connect_kwargs())
    di = psycopg2.connect(dbname="document_intelligence",
                          **{k: v for k, v in kw.items() if k != "dbname"})
    out = {}
    try:
        with di.cursor() as cur:
            cur.execute(
                """SELECT procurement_id, local_path, download_status
                   FROM document_files WHERE procurement_id = ANY(%s)""",
                (pids,),
            )
            for pid, path, status in cur.fetchall():
                out.setdefault(pid, []).append((path or "", status))
    finally:
        di.close()
    return out


def main() -> int:
    pids = direct_pids()
    fmap = files_map(pids)
    with_docs = [p for p in pids if any(s == "COMPLETED" and pp for pp, s in fmap.get(p, []))]
    print("direct=%d with_docs=%d" % (len(pids), len(with_docs)), flush=True)
    _r, _t, crm_db, warn = connect_databases()
    rows = []
    started_all = time.time()
    for idx, pid in enumerate(with_docs, 1):
        started = time.time()
        completed = [pp for pp, s in fmap.get(pid, []) if s == "COMPLETED" and pp]
        exts = {}
        for pp in completed:
            ext = os.path.splitext(pp)[1].lower().lstrip(".") or "?"
            exts[ext] = exts.get(ext, 0) + 1
        try:
            ext = load_direct_extraction(pid)
            dossier = load_procurement_dossier(crm_db, pid)
            tkp = build_tkp_request(ext, dossier)
            secs = sum(len(v or []) for v in (ext.get("sections") or {}).values())
            row = {"pid": pid, "files": len(completed), "exts": exts,
                   "spec": len(ext.get("spec") or []), "tech": len(ext.get("tech") or []),
                   "req": len(ext.get("requirements") or []), "sections": secs,
                   "tkp": len(tkp), "sec": round(time.time() - started, 2)}
        except Exception as exc:  # noqa: BLE001
            row = {"pid": pid, "files": len(completed), "exts": exts,
                   "error": "%s: %s" % (type(exc).__name__, exc)}
        rows.append(row)
        if idx % 50 == 0:
            print("progress %d/%d" % (idx, len(with_docs)), flush=True)
    with open(JSONL, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    ok = [r for r in rows if "error" not in r]
    with_spec = [r for r in ok if r["spec"]]
    with_tech = [r for r in ok if r["tech"]]
    with_any = [r for r in ok if r["spec"] or r["tech"] or r["sections"]]
    docx_no_spec = [r for r in ok if r["exts"].get("docx") and not r["spec"]]
    print("SUMMARY total=%d errors=%d with_spec=%d with_tech=%d with_any=%d docx_but_no_spec=%d wall=%ss" % (
        len(rows), len(rows) - len(ok), len(with_spec), len(with_tech), len(with_any),
        len(docx_no_spec), round(time.time() - started_all, 1)))
    print("no_docs_any: %s" % [r["pid"] for r in ok if not (r["spec"] or r["tech"] or r["sections"])][:25])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
