#!/usr/bin/env python3
"""Read-only production acceptance for fresh annotation filters and reset."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit"))
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89")]

from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

load_dotenv(ROOT / ".env", override=True)

WIDGET_KEYS = (
    "annotation_wb_queue_mode",
    "annotation_wb_annotation_status",
    "annotation_wb_model_source",
    "annotation_wb_publication_visibility",
    "annotation_wb_model_category",
)


def _run() -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=120)
    at.session_state["nav_page"] = "expert_annotation"
    return at.run(timeout=120)


def main() -> int:
    fresh = _run()
    metrics = {item.label: int(item.value) for item in fresh.metric}
    fresh_info = "\n".join(str(item.value) for item in fresh.info)

    reset = AppTest.from_file("app.py", default_timeout=120)
    reset.session_state["nav_page"] = "expert_annotation"
    reset.session_state["annotation_wb_filters"] = {
        "queue_mode": "all_current",
        "annotation_status": "annotated",
        "model_source": "legacy",
        "publication_visibility": "hidden",
        "model_category": "computers",
    }
    for key, value in zip(WIDGET_KEYS, ("all_current", "annotated", "legacy", "hidden", "computers")):
        reset.session_state[key] = value
    reset.run(timeout=120)
    next(item for item in reset.button if item.label == "Сбросить фильтры разметки").click().run(timeout=120)

    reset_filters = reset.session_state["annotation_wb_filters"]
    reset_widgets = {key: reset.session_state[key] for key in WIDGET_KEYS}
    out = {
        "exceptions": [str(item.value) for item in fresh.exception] + [str(item.value) for item in reset.exception],
        "total_open_assessed": metrics.get("Активные закупки с оценкой ИИ"),
        "current_filter_result": metrics.get("Текущий фильтр"),
        "fresh_publication_all": "publication: Все (gate не применяется)" in fresh_info,
        "reset_filters": reset_filters,
        "reset_widgets": reset_widgets,
        "reset_pass": reset_filters == {
            "queue_mode": "open_assessed",
            "annotation_status": "unannotated",
            "model_source": "all",
            "publication_visibility": "all",
            "model_category": "all",
        } and reset_widgets == {
            "annotation_wb_queue_mode": "open_assessed",
            "annotation_wb_annotation_status": "unannotated",
            "annotation_wb_model_source": "all",
            "annotation_wb_publication_visibility": "all",
            "annotation_wb_model_category": "all",
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not out["exceptions"] and out["fresh_publication_all"] and out["reset_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
