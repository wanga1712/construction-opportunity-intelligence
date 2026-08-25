#!/usr/bin/env python3
"""Read-only real-route acceptance for the first expert decision WIP."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

root = Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit"))
os.chdir(root)
sys.path[:0] = [str(root), os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89")]

from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

load_dotenv(root / ".env", override=True)

CONTROL_ID = 11235


def main() -> int:
    at = AppTest.from_file("app.py", default_timeout=240)
    at.session_state["nav_page"] = "objects_v2"
    at.run(timeout=240)
    stage = next(item for item in at.radio if "Идут торги" in list(item.options))
    stage.set_value("Идут торги").run(timeout=240)
    markdown = "\n".join(str(item.value) for item in at.markdown)
    initial_exceptions = [str(item.value) for item in at.exception]
    no_button = next(item for item in at.button if str(item.key).startswith("scope_no_"))
    visible_id = int(str(no_button.key).rsplit("_", 1)[1])
    no_button.click().run(timeout=240)
    after_no = "\n".join(str(item.value) for item in at.markdown)
    labels = [str(item.label) for item in [*at.text_input, *at.selectbox]]
    reason = next((item for item in at.selectbox if item.label.startswith("Почему?")), None)
    save_next = next((item for item in at.button if item.key == f"ann_{visible_id}_scope_no_save_next"), None)
    all_buttons = [str(item.label) for item in at.button]
    out = {
        "route": "app.py->objects_v2->Analytics Contour->Идут торги",
        "control_crm_id": CONTROL_ID,
        "visible_card_id": visible_id,
        "control_card_visible": visible_id == CONTROL_ID,
        "title_visible": "Поставка медицинских изделий (перчатки нитриловые)" in markdown,
        "amount_visible": "💰" in markdown,
        "deadline_visible": "📅" in markdown,
        "law_visible": "44-ФЗ" in markdown,
        "customer_visible": "НМИЦ пульмонологии" in markdown,
        "region_visible": "📍" in markdown,
        "okpd_visible": "ОКПД2" in markdown and "22.19" in markdown and "Изделия из резины прочие" in markdown,
        "procurement_link_visible": len(at.get("link_button")) > 0,
        "first_question_visible": "Закупка относится к нашему профилю?" in markdown,
        "scope_buttons_visible": all(value in all_buttons for value in ("✓ Да", "✕ Нет", "? Не уверен")),
        "fast_no_message": "Вне нашего профиля" in after_no or any(
            "Вне нашего профиля" in str(item.value) for item in at.error
        ),
        "fast_no_reason": reason is not None,
        "fast_no_save_next": save_next is not None,
        "advanced_accessible": any("Расширенная разметка" in str(value) for value in markdown.splitlines()) or any(
            "Экспертная разметка" in str(value) for group in at.get("button_group") for value in group.options
        ),
        "raw_labels_visible": any(value in labels for value in (
            "expert_object_type", "expert_object_subtype", "expert_work_stage", "annotation_review_scope"
        )),
        "exceptions": initial_exceptions + [str(item.value) for item in at.exception],
    }
    out["pass"] = all((
        out["control_card_visible"], out["title_visible"], out["amount_visible"], out["deadline_visible"], out["law_visible"],
        out["customer_visible"], out["region_visible"], out["okpd_visible"],
        out["procurement_link_visible"], out["first_question_visible"], out["scope_buttons_visible"],
        out["fast_no_message"], out["fast_no_reason"], out["fast_no_save_next"],
        out["advanced_accessible"], not out["raw_labels_visible"], not out["exceptions"],
    ))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
