"""Parse every Смета*.xlsx on disk: Форма 4б -> fixed map, others -> header map.

Unparsed layouts are recorded in estimate_template_registry so they can be
supported later. Read-only for facts; writes only the template registry.
"""
import os
import sys
import zipfile
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=True)
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/tender_documents_research")

import psycopg2  # noqa: E402

from document_processor.smeta_forma_4b import (  # noqa: E402
    detect_forma_4b,
    read_estimate,
    xlsx_sheet_names,
)
from document_processor.xlsx_table_reader import read_tables, template_signature  # noqa: E402

LIMIT = int(os.environ.get("EST_ALL_LIMIT", "1000"))


def _db(readonly: bool):
    kwargs = dict(
        host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
    )
    conn = psycopg2.connect(**kwargs)
    conn.set_session(readonly=readonly, autocommit=readonly)
    return conn


conn = _db(readonly=True)
cur = conn.cursor()
pattern = "%" + "\u0441\u043c\u0435\u0442\u0430" + "%.xlsx"
cur.execute(
    """SELECT procurement_id, file_name, local_path FROM document_files
       WHERE file_name ILIKE %s AND download_status='COMPLETED' AND local_deleted_at IS NULL
       ORDER BY procurement_id DESC LIMIT %s""",
    (pattern, LIMIT),
)
files = cur.fetchall()
print("FILES", len(files), flush=True)

stats = defaultdict(int)
unparsed = defaultdict(lambda: {"files": 0, "procs": set(), "sample": ""})
for pid, file_name, path in files:
    stats["seen"] += 1
    try:
        if not path or not os.path.exists(path):
            stats["missing_on_disk"] += 1
            continue
        if detect_forma_4b(xlsx_sheet_names(path)):
            facts = read_estimate(path)
            stats["forma4b"] += 1
        else:
            facts = read_tables(path)
            stats["generic"] += 1
        if facts:
            stats["facts"] += len(facts)
            stats["parsed"] += 1
        else:
            signature = template_signature(path)
            entry = unparsed[signature]
            entry["files"] += 1
            entry["procs"].add(pid)
            entry["sample"] = entry["sample"] or file_name
            stats["unparsed"] += 1
    except Exception as exc:
        stats["errors"] += 1
        print("ERR", pid, str(exc)[:70], flush=True)

print("STATS", dict(stats), flush=True)
print("UNPARSED_TEMPLATES", len(unparsed))
for signature, entry in sorted(unparsed.items(), key=lambda kv: -kv[1]["files"])[:15]:
    print("TPL", entry["files"], "files", len(entry["procs"]), "procs |",
          signature.encode("unicode_escape").decode("ascii")[:110])

write = _db(readonly=False)
wc = write.cursor()
wc.execute(
    """CREATE TABLE IF NOT EXISTS estimate_template_registry (
         signature text PRIMARY KEY,
         files_seen integer NOT NULL DEFAULT 0,
         procurements_seen integer NOT NULL DEFAULT 0,
         status text NOT NULL DEFAULT 'NEEDS_SUPPORT',
         sample_file text,
         first_seen_at timestamptz NOT NULL DEFAULT NOW(),
         last_seen_at timestamptz NOT NULL DEFAULT NOW()
       )"""
)
for signature, entry in unparsed.items():
    wc.execute(
        """INSERT INTO estimate_template_registry
             (signature, files_seen, procurements_seen, sample_file)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (signature) DO UPDATE
             SET files_seen = estimate_template_registry.files_seen + EXCLUDED.files_seen,
                 procurements_seen = GREATEST(estimate_template_registry.procurements_seen,
                                              EXCLUDED.procurements_seen),
                 last_seen_at = NOW()""",
        (signature, entry["files"], len(entry["procs"]), entry["sample"]),
    )
write.commit()
wc.execute("SELECT status, COUNT(*) FROM estimate_template_registry GROUP BY 1")
print("REGISTRY", wc.fetchall())
write.close()
conn.close()
