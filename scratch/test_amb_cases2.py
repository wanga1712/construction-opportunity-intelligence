import json
from src.services.ai_client import generate

SYSTEM_PROMPT = """Ты — строгий эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов и оборудования.
Твоя задача — проверить, подтверждает ли найденный фрагмент текста документа закупку, потребность, сметную строку, ведомость объемов или спецификацию на материалы/оборудование/работы целевой категории и подкатегории, указанных в блоке [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM].

ВНИМАНИЕ:
- Целевая проверка проводится строго на соответствие блоку [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM] (Категория и Подкатегория)!
- Менять категорию или подкатегорию ЗАПРЕЩЕНО.
- Наименование закупки в блоке [ТЕНДЕР] — это лишь общее название всего тендера, а не фильтр. Не путай название тендера с категорией товара!

КРИТЕРИИ ПРИНЯТИЯ РЕШЕНИЯ (decision):
1. CONFIRMED: Фрагмент документа прямо указывает на закупку, смету, ведомость объемов, ТЗ или применение целевого материала/оборудования указанной категории/подкатегории. ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ ДЛЯ CONFIRMED: указана конкретная марка, бренд, ГОСТ, химический тип или точная техническая спецификация (например: "ПВХ мембрана Пластфоил", "компаунд Денстоп ЭП-201", "сухая смесь Пенетрон", "смесь MasterTop 100", "состав MasterEmaco S 488", "материал Техноэласт ЭКП", "светильник ДКУ-100").
2. REJECTED: Совпадение очевидно ложное:
   - FUZZY_LEXICAL_COLLISION: созвучие слов ("ПРОЕКТ" вместо "проспект", "директор" вместо "вектор", "плотность" вместо "плотина").
   - ADDRESS_OR_LOCATION_ONLY: адрес, улица, город ("просп. Ленина", "ул. 3-я Магистральная").
   - ORGANIZATION_NAME_ONLY: наименование организации, должность ("ООО Вектор", "Генеральный директор").
   - LEGAL_ADMINISTRATIVE_TEXT: распоряжение, преамбула, типовой договор ("Распоряжением администрации...").
   - UNRELATED_PRODUCT: совершенно другой товар (медицинские шприцы/иглы для гидроизоляции, канцтовары, продукты, спецодежда).
   - NEGATIVE_PHRASE_CONTEXT: фрагмент содержит стоп-фразу.
3. UNKNOWN: Фрагмент содержит лишь общее родовое слово или обрезанную строку без указания конкретной марки, типа материала или точной спецификации (например: просто "мембрана", "покрытие", "пропитка", "состав", "герметик", "смесь" без марки и без подробных параметров). Поскольку марка и тип материала не указаны, невозможно однозначно подтвердить закупку целевого продукта -> decision: "UNKNOWN", confidence: 0.0, reason_code: "INSUFFICIENT_CONTEXT".

Ответ СТРОГО в формате JSON без markdown:
{
  "detail_id": <int/str>,
  "decision": "CONFIRMED" | "REJECTED" | "UNKNOWN",
  "confidence": <float 0.0-1.0>,
  "supporting_quote": "<дословная цитата из контекста>",
  "reason_code": "<SPECIFICATION_PRODUCT_REQUIREMENT|FUZZY_LEXICAL_COLLISION|ADDRESS_OR_LOCATION_ONLY|ORGANIZATION_NAME_ONLY|LEGAL_ADMINISTRATIVE_TEXT|UNRELATED_PRODUCT|NEGATIVE_PHRASE_CONTEXT|INSUFFICIENT_CONTEXT>",
  "reason": "<краткое объяснение>"
}"""

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
- Если указана конкретная марка/бренд/спецификация целевого материала -> 'CONFIRMED'.
- Если созвучие/адрес/другой нецелевой товар -> 'REJECTED'.
- Если указано лишь общее родовое слово без марки и спецификации, либо контекст обрезан -> 'UNKNOWN' (reason_code: 'INSUFFICIENT_CONTEXT', confidence: 0.0).
Ответь строго JSON."""

    full = f"{SYSTEM_PROMPT}\n\n{prompt}"
    res = generate(full, model="qwen2.5:7b", timeout=45, format_json=True)
    return res

cases = [
    # 1. Truncated cell: "герметик"
    {
        "procurement_id": 170001,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Строительные работы",
        "procurement_title": "Ремонт помещений здания",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "injection",
        "subcategory_name": "Инъекционная гидроизоляция",
        "matched_term": "герметик",
        "document_name": "Материалы.xlsx",
        "context_before": ["[Табличная ячейка без шапки таблицы и марки материала]"],
        "matched_line": "герметик строительный",
        "context_after": [],
    },
    # 2. Truncated fragment: "защитное покрытие"
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
        "context_before": ["[Поврежденный скан, марка покрытия и область применения отсутствуют]"],
        "matched_line": "защитное покрытие",
        "context_after": [],
    },
    # 3. Truncated cell: "пропитка"
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
        "matched_line": "пропитка по ведомости",
        "context_after": [],
    },
    # 4. Truncated drawing note: "мембрана"
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
        "context_before": ["[Оборванный фрагмент чертежа, марка мембраны не указана]"],
        "matched_line": "мембрана поз. 8",
        "context_after": [],
    },
    # 5. Truncated spec row: "состав"
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

print("TESTING 5 AMBIGUOUS WITH STRICT SPEC CRITERIA:")
for i, c in enumerate(cases):
    res = test_prompt(c)
    obj = json.loads(res)
    print(f"CASE {i+1} ({c['matched_term']}): Dec={obj.get('decision')}, Conf={obj.get('confidence')}, Reason={obj.get('reason_code')}")
