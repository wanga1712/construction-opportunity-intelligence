#!/usr/bin/env python3
"""Read-only S13 AppTest acceptance for the Phase C annotation card."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), "/opt/pythonProject89"]
from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

load_dotenv(ROOT / ".env", override=True)


def main() -> int:
    procurement_id = int(os.environ.get("PHASE_C_TEST_PID", "1013"))
    at = AppTest.from_file("app.py", default_timeout=120)
    at.session_state["nav_page"] = "expert_annotation"
    at.session_state["annotation_wb_queue"] = procurement_id
    at.run(timeout=120)
    tabs = [item.label for item in at.tabs]
    buttons = [item.label for item in at.button]
    markdown = "\n".join(str(item.value) for item in at.markdown)
    captions = "\n".join(str(item.value) for item in at.caption)
    infos = "\n".join(str(item.value) for item in at.info)
    warnings = "\n".join(str(item.value) for item in at.warning)
    link_buttons = [item.label for item in at.get("link_button")]
    out = {
        "procurement_id": procurement_id,
        "exceptions": [str(item.value) for item in at.exception],
        "tabs": tabs,
        "source_link_button": "🔗 Открыть закупку" in link_buttons,
        "header_source_law": "223-ФЗ" in markdown,
        "authority_sections": all(label in markdown for label in ("SOURCE FACTS", "MODEL", "BUSINESS RULE", "EXPERT")),
        "documents_empty_truthful": "Документные наблюдения" in infos,
        "history_has_real_assessment": "AI assessment v3" in markdown,
        "history_has_business_category": "Сформирована категория computers" in markdown,
        "legacy_warning": "Legacy" in warnings or "RAW модели не сохранён" in warnings,
        "actions": {label: label in buttons for label in (
            "✓ ВЕРНО", "✕ НЕВЕРНО", "+ ДОБАВИТЬ ПРОПУЩЕННУЮ КАТЕГОРИЮ",
            "💾 SAVE & NEXT →", "⛔ НЕ НАШ ПРОФИЛЬ",
        )},
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    required_tabs = {"Обзор", "Модель / Категории", "Документы", "История", "Экспертная разметка"}
    ok = (
        not out["exceptions"]
        and required_tabs.issubset(set(tabs))
        and out["source_link_button"]
        and out["header_source_law"]
        and out["authority_sections"]
        and out["history_has_real_assessment"]
        and out["history_has_business_category"]
        and all(out["actions"].values())
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
