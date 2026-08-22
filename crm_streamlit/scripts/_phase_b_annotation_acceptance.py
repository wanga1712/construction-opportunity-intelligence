#!/usr/bin/env python3
"""Phase B runtime acceptance — annotation queue counts on live CRM DB."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/opt/pythonProject89")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.annotation_queue_service import (
    AnnotationQueueFilters,
    ANNOTATION_FILTER_ALL,
    QUEUE_MODE_ALL_CURRENT,
    QUEUE_MODE_OPEN_ASSESSED,
    fetch_queue_counters,
    fetch_queue_ids,
    batch_publication_visibility,
)


def main() -> int:
    _, _, crm_db, warn = connect_databases()
    print("DB_WARN", warn)
    counters = fetch_queue_counters(crm_db)
    open_ids = fetch_queue_ids(crm_db, AnnotationQueueFilters(
        queue_mode=QUEUE_MODE_OPEN_ASSESSED,
        annotation_status=ANNOTATION_FILTER_ALL,
    ))
    all_ids = fetch_queue_ids(crm_db, AnnotationQueueFilters(
        queue_mode=QUEUE_MODE_ALL_CURRENT,
        annotation_status=ANNOTATION_FILTER_ALL,
    ))
    vis = batch_publication_visibility(crm_db, open_ids)
    visible = sum(1 for v in vis.values() if v)
    hidden = sum(1 for v in vis.values() if not v)
    out = {
        "counters": counters,
        "default_open_assessed_queue_count": len(open_ids),
        "all_current_assessments_queue_count": len(all_ids),
        "open_assessed_publication_visible": visible,
        "open_assessed_publication_hidden": hidden,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    ok = (
        counters.get("open_assessed") == len(open_ids)
        and counters.get("all_current_assessments") == len(all_ids)
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
