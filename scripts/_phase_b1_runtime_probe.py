#!/usr/bin/env python3
"""Phase B.1 — probe actual annotation page queue + UI module markers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/opt/pythonProject89")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.annotation_queue_service import (
    ANNOTATION_FILTER_ALL,
    ANNOTATION_FILTER_UNANNOTATED,
    AnnotationQueueFilters,
    fetch_queue_counters,
    fetch_queue_ids,
)

MARKERS = {
    "workbench_title": "РАЗМЕТКА",
    "fast_category_block": "Категории — быстрая разметка",
    "old_verdict_block": "Оценка эксперта",
}


def _file_markers(rel: str) -> dict[str, int]:
    p = ROOT / rel
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    return {k: text.count(v) for k, v in MARKERS.items()}


def main() -> int:
    from src.services.db_bootstrap import connect_databases

    _, _, crm, _ = connect_databases()
    counters = fetch_queue_counters(crm)
    default_filters = AnnotationQueueFilters()
    default_ids = fetch_queue_ids(crm, default_filters)
    all_open_assessed = fetch_queue_ids(
        crm,
        AnnotationQueueFilters(annotation_status=ANNOTATION_FILTER_ALL),
    )
    pub_visible_ids = fetch_queue_ids(
        crm,
        AnnotationQueueFilters(
            annotation_status=ANNOTATION_FILTER_ALL,
            publication_visibility="visible",
        ),
    )
    out = {
        "git_head": (ROOT / ".git").exists(),
        "files": {
            "annotation_workbench_page.py": _file_markers("src/ui/annotation_workbench_page.py"),
            "annotation_card.py": _file_markers("src/ui/components/analytics_v2/annotation_card.py"),
            "card_tabs_ai.py": _file_markers("src/ui/components/analytics_v2/card_tabs_ai.py"),
        },
        "counters": counters,
        "queue_default_unannotated_open_assessed": len(default_ids),
        "queue_all_open_assessed": len(all_open_assessed),
        "queue_pub_visible_open_assessed": len(pub_visible_ids),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
