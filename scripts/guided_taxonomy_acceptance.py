"""Read-only real-route AppTest for guided taxonomy selectors."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
load_dotenv(root / ".env", override=True)

CONTROL_ID = 64132
CONTROL_PAGE = 100


def main() -> int:
    at = AppTest.from_file(str(root / "app.py"), default_timeout=240)
    at.run(timeout=240)
    next(item for item in at.radio if "Идут торги" in list(item.options)).set_value("Идут торги").run(timeout=240)
    next(item for item in at.number_input if item.label == "Страница").set_value(CONTROL_PAGE).run(timeout=240)
    yes = next((item for item in at.button if item.key == f"scope_yes_{CONTROL_ID}"), None)
    if yes is None:
        print(json.dumps({"page": CONTROL_PAGE, "scope_yes_keys": [
            item.key for item in at.button if str(item.key).startswith("scope_yes_")
        ]}, ensure_ascii=False, indent=2))
        return 2
    yes.click().run(timeout=240)

    category = next((item for item in at.multiselect if item.label == "Категории"), None)
    if category is not None:
        category.set_value(["lighting"]).run(timeout=240)
    markdown = "\n".join(str(item.value) for item in at.markdown)
    select_labels = [str(item.label) for item in at.selectbox]
    text_labels = [str(item.label) for item in at.text_input]
    medal = next((item for item in at.selectbox if item.label == "Медаль"), None)
    result = {
        "route": "app.py->objects_v2->Analytics Contour->Идут торги",
        "control_crm_id": CONTROL_ID,
        "first_scope_gate": "Закупка относится к нашему профилю?" in markdown,
        "category_selector": category is not None,
        "category_option_count": len(category.options) if category is not None else 0,
        "registry_category_selected": category is not None and "lighting" in list(category.value),
        "subcategory_selector": any(label.startswith("Подкатегория —") for label in select_labels),
        "object_selector": "Тип объекта" in select_labels,
        "object_subtype_selector": "Подтип / уточнение объекта" in select_labels,
        "work_stage_selector": "Стадия / вид работ" in select_labels,
        "medal_selector": medal is not None and list(medal.options) == [
            "Не выбрано", "🥇 GOLD", "🥈 SILVER", "🥉 BRONZE", "🪵 WOOD"
        ],
        "medal_options": list(medal.options) if medal is not None else [],
        "english_placeholder": "Choose an option" in markdown,
        "primary_giant_text_inputs": any(label in {"Тип объекта", "Подтип / уточнение объекта", "Стадия / вид работ"} for label in text_labels),
        "exceptions": [str(item.value) for item in at.exception],
    }
    result["pass"] = all((
        result["first_scope_gate"], result["category_selector"], result["category_option_count"] == 14,
        result["registry_category_selected"], result["subcategory_selector"], result["object_selector"],
        result["object_subtype_selector"], result["work_stage_selector"], result["medal_selector"],
        not result["english_placeholder"], not result["primary_giant_text_inputs"], not result["exceptions"],
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
