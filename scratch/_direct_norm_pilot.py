"""Пилот ИИ-нормализации позиций сметы DIRECT (read-only, без записи в прод).

Берёт позиции спецификации закупки, отдаёт локальной модели список категорий
реестра и просит строгий JSON: нормализованное имя + категория/подкатегория +
confidence. Результат печатается, никуда не сохраняется.
"""
import json
import sys
import urllib.request

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.direct_document_extractor import load_direct_extraction  # noqa: E402
from src.services.manual_category_service import list_categories  # noqa: E402

MODEL = "qwen2.5:7b"
URL = "http://127.0.0.1:11434/api/generate"


def ask(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0}}).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8")).get("response", "")


def main() -> int:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 459631
    data = load_direct_extraction(pid)
    spec = data.get("spec") or []
    tech = data.get("tech") or []
    items = []
    for it in spec:
        cells = it.get("cells") or []
        name = next((c for c in cells if c and len(c) > 5), "")
        if name and name.lower() not in ("итого",):
            items.append(name)
    cats = list_categories(db=None)
    cat_list = "; ".join(f'{c["category_code"]}={c.get("category_name")}' for c in cats)
    prompt = (
        "Ты нормализуешь позиции сметы закупки. Для каждой позиции верни СТРОГО JSON-массив "
        'объектов вида {"raw": "...", "normalized": "...", "category_code": "...", '
        '"subcategory_hint": "...", "confidence": 0..1}.\n'
        f"Разрешённые категории: {cat_list}.\n"
        "Если позиция не относится ни к одной — category_code = \"OTHER\".\n\n"
        "Позиции:\n" + "\n".join(f"- {x}" for x in items[:20]) + "\n\nJSON:"
    )
    print("SPEC_ITEMS=", len(items), "| TECH_ROWS=", len(tech))
    out = ask(prompt)
    print("MODEL_RAW:")
    print(out[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
