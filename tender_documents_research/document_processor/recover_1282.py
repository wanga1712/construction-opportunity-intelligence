from backends.s13_queue import S13V2QueueBackend
import os

dsn = {
    "dsn": "postgresql://doc_worker:docS13v2!@localhost:5432/document_intelligence"
}
queue = S13V2QueueBackend(dsn)
queue.mark_pending(1282)
print("Recovered task 1282 to PENDING using official repository method.")