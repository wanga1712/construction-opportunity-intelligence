"""Mark queue rows whose files are all excluded by the file policy.

Terminal status SKIPPED_NOISE (not claimed by workers), so 18k+ FAILED rows made
of contract drafts / notices / platform artifacts stop burning worker time.
"""
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=True)
sys.path.insert(0, "/opt/tender_documents_research")

import psycopg2  # noqa: E402

from document_processor.file_skip_list import should_skip_file  # noqa: E402

conn = psycopg2.connect(
    host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
    dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
)
cur = conn.cursor()
cur.execute(
    """SELECT q.id, f.file_name
       FROM document_processing_queue q
       JOIN document_files f ON f.queue_id = q.id
       WHERE q.status IN ('FAILED','PENDING','PRE_RESEARCH_WAITING')"""
)
by_queue = defaultdict(list)
for queue_id, file_name in cur.fetchall():
    by_queue[queue_id].append(file_name)
print("QUEUE_ROWS_WITH_FILES", len(by_queue), flush=True)

noise = [
    queue_id
    for queue_id, names in by_queue.items()
    if names and all(should_skip_file(name) for name in names)
]
print("NOISE_ROWS", len(noise), flush=True)

for start in range(0, len(noise), 2000):
    chunk = [(i,) for i in noise[start:start + 2000]]
    cur.executemany(
        """UPDATE document_processing_queue
             SET status='SKIPPED_NOISE', completed_at=NOW(), worker_id=NULL,
                 last_error='SKIPPED_BY_FILE_POLICY'
           WHERE id=%s""",
        chunk,
    )
    conn.commit()
    print("MARKED", start + len(chunk), flush=True)

cur.execute("SELECT status, COUNT(*) FROM document_processing_queue GROUP BY 1 ORDER BY 2 DESC")
print("QUEUE_AFTER", cur.fetchall())
conn.close()
