import os
import sys
import subprocess
import datetime
import hashlib
import json

ARCHIVE_ID = f"clean_slate_pre_v4_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
ARCHIVE_BASE_DIR = f"/opt/tender_documents_research_archive/{ARCHIVE_ID}"
DB_ARCHIVE_DIR = f"{ARCHIVE_BASE_DIR}/db_backups"
FILE_ARCHIVE_DIR = f"{ARCHIVE_BASE_DIR}/files"

os.makedirs(DB_ARCHIVE_DIR, exist_ok=True)
os.makedirs(FILE_ARCHIVE_DIR, exist_ok=True)

# 1. Dump document_intelligence DB
doc_db_dump_path = f"{DB_ARCHIVE_DIR}/document_intelligence_backup.sql"
subprocess.run(
    f"PGPASSWORD=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT pg_dump -h 127.0.0.1 -p 5432 -U doc_worker -d document_intelligence -F p -f {doc_db_dump_path}",
    shell=True,
    check=True,
)

# 2. Dump CRM DB
crm_db_dump_path = f"{DB_ARCHIVE_DIR}/crm_v3_derived_backup.sql"
subprocess.run(
    f"PGPASSWORD=X17B3n5hbANQSRt6i7WIyy0lJudX pg_dump -h 127.0.0.1 -p 5432 -U crm_app -d crm -t 'crm_v3_*' -F p -f {crm_db_dump_path}",
    shell=True,
    check=True,
)

# SHA256 hashes
def get_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

doc_sha256 = get_sha256(doc_db_dump_path)
crm_sha256 = get_sha256(crm_db_dump_path)

# 3. Archive physical research files
source_research_dir = "/opt/tender_documents_research"
archived_files_count = 0
archived_bytes = 0

if os.path.exists(source_research_dir):
    subprocess.run(
        f"cp -rp {source_research_dir}/* {FILE_ARCHIVE_DIR}/ 2>/dev/null || true",
        shell=True,
    )
    for root, dirs, files in os.walk(FILE_ARCHIVE_DIR):
        for f in files:
            archived_files_count += 1
            archived_bytes += os.path.getsize(os.path.join(root, f))

info = {
    "ARCHIVE_ID": ARCHIVE_ID,
    "ARCHIVE_BASE_DIR": ARCHIVE_BASE_DIR,
    "DB_ARCHIVE_PATHS": [doc_db_dump_path, crm_db_dump_path],
    "DB_ARCHIVE_SHA256": {
        "document_intelligence": doc_sha256,
        "crm_v3": crm_sha256,
    },
    "FILE_ARCHIVE_PATH": FILE_ARCHIVE_DIR,
    "FILES_ARCHIVED": archived_files_count,
    "BYTES_ARCHIVED": archived_bytes,
}

print("=== ARCHIVE COMPLETED ===")
print(json.dumps(info, indent=2))

with open(f"{ARCHIVE_BASE_DIR}/archive_manifest.json", "w") as f:
    json.dump(info, f, indent=2)
