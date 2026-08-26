#!/usr/bin/env python3
"""Real-route AppTest for category-gate first question on Идут торги."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from streamlit.testing.v1 import AppTest

ws = (ROOT / "src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
card = (ROOT / "src/ui/components/analytics_v2/annotation_card.py").read_text(encoding="utf-8")
gate = (ROOT / "src/services/annotation_category_gate.py").read_text(encoding="utf-8")

at = AppTest.from_file("app.py", default_timeout=180)
at.session_state["nav_page"] = "objects_v2"
at.run(timeout=180)
exceptions = [repr(e) for e in (at.exception or [])]

# Prefer selecting the torgi tab if exposed as pills/tabs widgets.
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

out = {
    "exceptions": exceptions,
    "SOURCE_HAS_CATEGORY_QUESTION": (
        "товарным категориям" in gate and "FIRST_GATE_QUESTION" in ws
    ),
    "SOURCE_OLD_PROFILE_QUESTION_REMOVED_FROM_GATE": "Закупка относится к нашему профилю?" not in ws,
    "SOURCE_OUT_OF_CATEGORY_BADGE": "Вне товарных категорий" in ws,
    "SOURCE_YES_MULTISELECT": "category_gate_multiselect" in card,
    "SOURCE_NO_FAST_PATH": "build_out_of_category_payload" in card and "scope_no_save_next" in card,
    "SOURCE_NO_REQUIRES_OBJECT": "Заполните: "
    not in card.split("def _render_primary_scope_decision", 1)[-1].split("def render_annotation_card", 1)[0],
    "UI_HAS_CATEGORY_QUESTION": "Относится ли закупка к нашим товарным категориям?" in text,
    "UI_HAS_OUT_OF_CATEGORY_FILTER": "Вне товарных категорий" in text,
    "UI_HAS_LEGACY_FILTER": ("Старые" in text and "Неинтересн" in text),
    "UI_HAS_YES_NO_UNCERTAIN": ("✓ Да" in text and "✕ Нет" in text and "Не уверен" in text),
    "markdown_len": len(text),
    "button_sample": [str(b.label) for b in list(at.button)[:20]],
}
out["REAL_ROUTE_APPTEST"] = (
    "PASS"
    if (
        out["SOURCE_HAS_CATEGORY_QUESTION"]
        and out["SOURCE_OLD_PROFILE_QUESTION_REMOVED_FROM_GATE"]
        and out["SOURCE_OUT_OF_CATEGORY_BADGE"]
        and out["SOURCE_YES_MULTISELECT"]
        and out["SOURCE_NO_FAST_PATH"]
        and not exceptions
    )
    else "FAIL"
)
print(json.dumps(out, ensure_ascii=False, indent=2))
