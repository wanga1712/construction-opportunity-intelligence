import json
from src.services.ai_client import generate
from tender_documents_research.document_processor.context_validator import SYSTEM_PROMPT

def test_prompt(candidate):
    cat_name = candidate["category_name"]
    cat_code = candidate["category_code"]
    sub_name = candidate["subcategory_name"]
    sub_code = candidate["subcategory_code"]
    term = candidate["matched_term"]
    matched_line = candidate["matched_line"]
    before = "\n".join(candidate.get("context_before") or [])
    after = "\n".join(candidate.get("context_after") or [])

    prompt = f"""[ТЕНДЕР]
ID: {candidate['procurement_id']}
ОКПД2: {candidate['procurement_okpd_code']} ({candidate['procurement_okpd_name']})
Наименование закупки: {candidate['procurement_title']}

[ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]
Категория: {cat_name} ({cat_code})
Подкатегория: {sub_name} ({sub_code})
Искомый термин: {term}
Документ: {candidate['document_name']}

[КОНТЕКСТ ИЗ ДОКУМЕНТА]
{before}
>>> НАЙДЕННАЯ СТРОКА: {matched_line}
{after}

[ВОПРОС]
Подтверждает ли данный фрагмент документа закупку/применение материалов для подкатегории "{sub_name}" (категория "{cat_name}", термин "{term}")?
- Если прямо указана целевая закупка/спецификация/марка материала -> 'CONFIRMED'.
- Если созвучие/адрес/другой нецелевой товар -> 'REJECTED'.
- Если контекст обрезан, представляет собой отдельное общее слово или обрывок фразы без конкретной марки и области применения -> 'UNKNOWN' (confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT').
Ответь строго JSON."""

    full = f"{SYSTEM_PROMPT}\n\n{prompt}"
    res = generate(full, model="qwen2.5:7b", timeout=45, format_json=True)
    return res

cases = [
    # 1. Truncated cell: "герметизация" for penetrating waterproofing
    {
        "procurement_id": 170001,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Ремонт помещений здания",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "penetrating",
        "subcategory_name": "Проникающая гидроизоляция",
        "matched_term": "герметизация",
        "document_name": "Материалы.xlsx",
        "context_before": ["[Табличная ячейка без заголовка и характеристик]"],
        "matched_line": "герметизация швов и стыков",
        "context_after": [],
    },
    # 2. Truncated fragment: "защитное покрытие" for polymer self-leveling floors
    {
        "procurement_id": 170002,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Ремонт объекта",
        "category_code": "flooring",
        "category_name": "Напольные покрытия",
        "subcategory_code": "polymer_self_leveling",
        "subcategory_name": "Полимерные наливные полы",
        "matched_term": "покрытие",
        "document_name": "ТЗ.docx",
        "context_before": ["[Поврежденный скан, текст строки обрезан]"],
        "matched_line": "защитное покрытие",
        "context_after": [],
    },
    # 3. Truncated cell: "пропитка" for penetrating waterproofing
    {
        "procurement_id": 170003,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Строительство корпуса",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "penetrating",
        "subcategory_name": "Проникающая гидроизоляция",
        "matched_term": "пропитка",
        "document_name": "Ведомость.xlsx",
        "context_before": ["[Табличная ячейка без указания типа и состава пропитки]"],
        "matched_line": "пропитка бетонной поверхности",
        "context_after": [],
    },
    # 4. Truncated drawing note: "мембрана" for membrane waterproofing
    {
        "procurement_id": 170004,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Строительство склада",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "membrane",
        "subcategory_name": "Мембранная гидроизоляция",
        "matched_term": "мембрана",
        "document_name": "Чертеж_фрагмент.pdf",
        "context_before": ["[Оборванный фрагмент сноски на чертеже, тип мембраны не указан]"],
        "matched_line": "укладка мембраны согл. узлу 4",
        "context_after": [],
    },
    # 5. Truncated spec row: "ремонтный состав" for concrete repair
    {
        "procurement_id": 170005,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Ремонт цеха",
        "category_code": "waterproofing_concrete_repair",
        "category_name": "Гидроизоляция и ремонт бетона",
        "subcategory_code": "concrete_repair",
        "subcategory_name": "Конструкционный ремонт бетона",
        "matched_term": "состав",
        "document_name": "Смета.xlsx",
        "context_before": ["[Строка спецификации без марки и параметров]"],
        "matched_line": "специальный состав",
        "context_after": [],
    }
]

for i, c in enumerate(cases):
    res = test_prompt(c)
    obj = json.loads(res)
    print(f"CASE {i+1} ({c['matched_term']}): Dec={obj.get('decision')}, Conf={obj.get('confidence')}, Reason={obj.get('reason_code')}")
