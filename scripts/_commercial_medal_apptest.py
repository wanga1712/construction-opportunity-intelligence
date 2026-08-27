#!/usr/bin/env python3
"""Real-route AppTest for commercial/medal staged annotation."""
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
ui = (ROOT / "src/ui/components/analytics_v2/staged_annotation_ui.py").read_text(encoding="utf-8")
entry = (ROOT / "src/services/expert_commercial_entry.py").read_text(encoding="utf-8")
medal = (ROOT / "src/services/expert_medal_stage.py").read_text(encoding="utf-8")

at = AppTest.from_file("app.py", default_timeout=180)
at.session_state["nav_page"] = "objects_v2"
at.run(timeout=180)
exceptions = [repr(e) for e in (at.exception or [])]

for r in list(at.radio):
    opts = list(r.options)
    if any("Идут торги" in str(o) for o in opts):
        r.set_value(next(o for o in opts if "Идут торги" in str(o))).run(timeout=180)
        break

for b in list(at.button):
    if str(b.label).startswith("Разметить"):
        b.click().run(timeout=180)
        break

chunks = []
for attr in ("markdown", "caption"):
    for item in list(getattr(at, attr, []) or []):
        chunks.append(str(getattr(item, "value", "") or ""))
text = "\n".join(chunks)

out = {
    "exceptions": exceptions,
    "SOURCE_COMMERCIAL_ENTRY": "expert_commercial_entry" in entry,
    "SOURCE_MEDAL_STAGE": "MEDAL_VALUES" in medal and "NCE" in medal,
    "SOURCE_SUBCATEGORY_UI": "render_product_category_controls" in ui,
    "SOURCE_COMMERCIAL_UI": "render_commercial_and_medal_controls" in ui,
    "SOURCE_YES_USES_COMMERCIAL": "render_commercial_and_medal_controls" in card,
    "SOURCE_OUT_NO_MEDAL_REQUIRED": "коммерческая оценка, медаль" in card.lower()
    or "Категория, коммерческая оценка, медаль" in card,
    "SOURCE_FILTERS_COMMERCIAL": "Коммерчески подходит" in ws,
    "UI_HAS_OBJECT": "Что это за объект" in text,
    "UI_HAS_MODE": "Что закупают" in text,
    "UI_HAS_CATEGORY_GATE": "товарным категориям" in text,
    "UI_HAS_SOURCE": ("223-ФЗ" in text or "44-ФЗ" in text),
}
out["REAL_ROUTE_APPTEST"] = (
    "PASS"
    if (
        out["SOURCE_COMMERCIAL_ENTRY"]
        and out["SOURCE_MEDAL_STAGE"]
        and out["SOURCE_SUBCATEGORY_UI"]
        and out["SOURCE_COMMERCIAL_UI"]
        and out["SOURCE_YES_USES_COMMERCIAL"]
        and not exceptions
    )
    else "FAIL"
)
print(json.dumps(out, ensure_ascii=False, indent=2))
