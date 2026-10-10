"""Show docx/xlsx table header signatures for DIRECT pids where spec was not detected."""
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.direct_document_extractor import _is_junk, _tables_for, load_direct_extraction

JSONL = "/tmp/direct_batch.jsonl"
MAX_PIDS = int(os.getenv("PROBE_PIDS", "6"))

rows = [json.loads(l) for l in open(JSONL, encoding="utf-8") if l.strip()]
targets = [r for r in rows if r.get("exts", {}).get("docx") and not r.get("spec")][:MAX_PIDS]
print("targets:", [r["pid"] for r in targets])

for row in targets:
    pid = row["pid"]
    ext = load_direct_extraction(pid)
    print("=== pid %s files=%s exts=%s spec=%s tech=%s sect=%s" % (
        pid, row.get("files"), row.get("exts"), row.get("spec"), row.get("tech"), row.get("sections")))
    paths = []
    try:
        from src.services.direct_document_extractor import _di_conn
        conn = _di_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT local_path FROM document_files
                       WHERE procurement_id=%s AND download_status='COMPLETED' AND local_path IS NOT NULL""",
                    (pid,),
                )
                paths = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        print("   di err", exc)
    for path in paths:
        if not path or not os.path.exists(path) or _is_junk(path):
            continue
        tables = _tables_for(path)
        print("   %s tables=%d" % (os.path.basename(path), len(tables)))
        for t in tables[:6]:
            head = " | ".join(c for c in (t[0] if t else []) if c)[:170]
            print("      rows=%d head=%s" % (len(t), head))
    if len(paths) > 6:
        print("   ...(+%d files)" % (len(paths) - 6))
