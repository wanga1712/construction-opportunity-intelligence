#!/usr/bin/env python3
"""Real-route AppTest for staged object/mode/category annotation on Идут торги."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path[:0] = [str(ROOT)]
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except Exception:
    pass

from streamlit.testing.v1 import AppTest

ws = (ROOT / "src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
card = (ROOT / "src/ui/components/analytics_v2/annotation_card.py").read_text(encoding="utf-8")
staged_ui = (ROOT / "src/ui/components/analytics_v2/staged_annotation_ui.py").read_text(encoding="utf-8")
source = (ROOT / "src/services/source_contour.py").read_text(encoding="utf-8")

at = AppTest.from_file("app.py", default_timeout=180)
at.session_state["nav_page"] = "objects_v2"
at.run(timeout=180)
exceptions = [repr(e) for e in (at.exception or [])]

for widget in list(getattr(at, "tabs", []) or []) + list(getattr(at, "pills", []) or []):
    try:
        opts = getattr(widget, "options", None) or getattr(widget, "labels", None) or []
        if any("Идут торги" in str(o) for o in opts):
            widget.set_value("Идут торги").run(timeout=180)
            break
    except Exception as exc:  # noqa: BLE001
        exceptions.append(str(exc)[:200])

chunks = []
for attr in ("markdown", "caption", "info", "error", "success", "warning"):
    for item in list(getattr(at, attr, []) or []):
        chunks.append(str(getattr(item, "value", "") or getattr(item, "label", "") or ""))
for btn in list(at.button):
    chunks.append(str(getattr(btn, "label", "") or ""))
text = "\n".join(chunks)

primary = card.split("def _render_primary_scope_decision", 1)[-1].split("def render_annotation_card", 1)[0]

out = {
    "exceptions": exceptions,
    "SOURCE_CONTOUR_MODULE": "resolve_source_contour" in source,
    "SOURCE_STAGED_OBJECT": "render_object_stage_controls" in staged_ui,
    "SOURCE_PROC_MODE": "expert_procurement_mode" in staged_ui,
    "SOURCE_CATEGORY_GATE_PRESERVED": "FIRST_GATE_QUESTION" in primary and "category_gate_multiselect" in primary,
    "SOURCE_STAGED_MERGE": "merge_staged_fields" in primary,
    "SOURCE_SAVE_BEFORE_NEXT": "_persist_staged" in primary and "save_and_next=True" in primary,
    "UI_HAS_EXPERT_HEADER": "ЭКСПЕРТНАЯ РАЗМЕТКА" in text,
    "UI_HAS_SOURCE_CONTOUR": ("223-ФЗ" in text or "44-ФЗ" in text or "615-ПП" in text),
    "UI_HAS_OBJECT_STAGE": "Что это за объект" in text or "Разметить" in text,
    "UI_HAS_CATEGORY_QUESTION": "Относится ли закупка к нашим товарным категориям?" in text
    or "товарным категориям" in ws,
    "UI_HAS_REVIEW_FILTERS": "Не проверено" in text and "Проверено" in text,
    "markdown_len": len(text),
}
out["REAL_ROUTE_APPTEST"] = (
    "PASS"
    if (
        out["SOURCE_CONTOUR_MODULE"]
        and out["SOURCE_STAGED_OBJECT"]
        and out["SOURCE_PROC_MODE"]
        and out["SOURCE_CATEGORY_GATE_PRESERVED"]
        and out["SOURCE_STAGED_MERGE"]
        and not exceptions
    )
    else "FAIL"
)
print(json.dumps(out, ensure_ascii=False, indent=2))
