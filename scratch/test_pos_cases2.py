import json
from src.services.ai_client import generate
from tender_documents_research.document_processor.context_validator import ContextValidator

SYSTEM_PROMPT = """Ты — строгий эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов и оборудования.
Твоя задача — проверить, подтверждает ли найденный фрагмент текста документа закупку, потребность, сметную строку, ведомость объемов или спецификацию на материалы/оборудование/работы целевой категории и подкатегории, указанных в блоке [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM].

ВНИМАНИЕ:
- Целевая проверка проводится строго на соответствие блоку [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM] (Категория и Подкатегория)!
- Менять категорию или подкатегорию ЗАПРЕЩЕНО.
- Наименование закупки в блоке [ТЕНДЕР] — это лишь общее название всего тендера, а не фильтр. Не путай название тендера с категорией товара!

КРИТЕРИИ ПРИНЯТИЯ РЕШЕНИЯ (decision):
1. CONFIRMED: Фрагмент документа прямо указывает на закупку, смету, ведомость объемов, ТЗ или применение целевого материала/оборудования указанной категории/подкатегории. ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ ДЛЯ CONFIRMED: указана конкретная марка, бренд, ГОСТ, химический тип или точная техническая спецификация (например: "ПВХ мембрана Пластфоил", "компаунд Денстоп ЭП-201", "сухая смесь Пенетрон", "смесь MasterTop 100", "состав MasterEmaco S 488", "материал Техноэласт ЭКП", "светильник ДКУ-100", "лоток полимеркомпозитный").
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

validator = ContextValidator(
    model="qwen2.5:7b",
    confirm_threshold=0.80,
    reject_threshold=0.85,
    ai_caller=lambda p: generate(f"{SYSTEM_PROMPT}\n\n{p}", model="qwen2.5:7b", timeout=45, format_json=True)
)

positive_canaries = [
    {
        "detail_id": 2001,
        "procurement_id": 165094,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Ремонт цеха",
        "category_code": "flooring",
        "category_name": "Напольные покрытия",
        "subcategory_code": "polymer_self_leveling",
        "subcategory_name": "Полимерные наливные полы",
        "matched_term": "денстоп",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Ведомость_работ.xlsx",
        "page_or_sheet": "Лист 1",
        "row_number": 42,
        "context_before": ["Устройство финишного полимерного покрытия пола в производственном помещении."],
        "matched_line": "Нанесение самонивелирующегося эпоксидного компаунда Денстоп ЭП-201 толщиной 2.5 мм",
        "context_after": ["Расход материала 3.2 кг/м2."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2002,
        "procurement_id": 165095,
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники",
        "procurement_title": "Модернизация уличного освещения",
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "road_street",
        "subcategory_name": "Уличное освещение",
        "matched_term": "светильник уличный",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Спецификация.pdf",
        "page_or_sheet": "2",
        "row_number": 10,
        "context_before": ["Спецификация оборудования к закупке:"],
        "matched_line": "Светильник уличный консольный светодиодный ДКУ-100/14000лм IP67",
        "context_after": ["Количество: 120 шт. Гарантия 5 лет."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2003,
        "procurement_id": 165096,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Гидроизоляция подземного паркинга",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "penetrating",
        "subcategory_name": "Проникающая гидроизоляция",
        "matched_term": "пенетрон",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Локальная_смета.xlsx",
        "page_or_sheet": "Смета 02-01",
        "row_number": 88,
        "context_before": ["Обработка бетонных поверхностей заглубленных конструкций:"],
        "matched_line": "Гидроизоляция бетонных стен сухой смесью Пенетрон в 2 слоя с расходом 1.0 кг/м2",
        "context_after": ["Увлажнение бетона перед нанесением."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2004,
        "procurement_id": 165097,
        "procurement_okpd_code": "42.11.20.000",
        "procurement_okpd_name": "Строительство дорог",
        "procurement_title": "Строительство автодороги",
        "category_code": "composites",
        "category_name": "Композитные материалы",
        "subcategory_code": "drainage_tray",
        "subcategory_name": "Композитные водоотводные лотки",
        "matched_term": "водоотводный лоток",
        "match_method": "COMPOUND_RULE",
        "score": 100.0,
        "document_name": "ТЗ_водоотвод.pdf",
        "page_or_sheet": "4",
        "row_number": 23,
        "context_before": ["Система поверхностного водоотвода вдоль обочины:"],
        "matched_line": "Лоток водоотводный полимеркомпозитный DN150 с чугунной решеткой щелевой",
        "context_after": ["Класс нагрузки С250, длина 1000 мм."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2005,
        "procurement_id": 165098,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Капитальный ремонт бассейна",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "membrane",
        "subcategory_name": "Мембранная гидроизоляция",
        "matched_term": "пвх мембрана",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Спецификация_материалов.pdf",
        "page_or_sheet": "3",
        "row_number": 14,
        "context_before": ["Материалы для гидроизоляции чаши:"],
        "matched_line": "Кровельная ПВХ мембрана Пластфоил F1.5 толщиной 1.5 мм",
        "context_after": ["Монтаж методом сварки горячим воздухом."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2006,
        "procurement_id": 165099,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Ремонт деформационных швов моста",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "injection",
        "subcategory_name": "Инъекционная гидроизоляция",
        "matched_term": "инъекционная смола",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Техкарта_инъектирование.docx",
        "page_or_sheet": "1",
        "row_number": 30,
        "context_before": ["Устранение фильтрации грунтовых вод через технологические швы:"],
        "matched_line": "Инъекционная смола полиуретановая двухкомпонентная Манопур 143 для гидроизоляции швов",
        "context_after": ["Инъектирование через пакера 13х110 мм под давлением до 150 бар."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2007,
        "procurement_id": 165100,
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники",
        "procurement_title": "Освещение производственного склада",
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "industrial",
        "subcategory_name": "Промышленное освещение",
        "matched_term": "светильник промышленный",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Опросный_лист.pdf",
        "page_or_sheet": "1",
        "row_number": 5,
        "context_before": ["Номенклатура светильников:"],
        "matched_line": "Светильник промышленный подвесной светодиодный high-bay 150W 5000K IP65",
        "context_after": ["Крепление на трос, угол рассеивания 90 градусов."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2008,
        "procurement_id": 165101,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Устройство топпинговых полов",
        "category_code": "flooring",
        "category_name": "Напольные покрытия",
        "subcategory_code": "dry_shake_topping",
        "subcategory_name": "Топпинг для бетонных полов",
        "matched_term": "топпинг",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "ТЗ_полы.pdf",
        "page_or_sheet": "2",
        "row_number": 19,
        "context_before": ["Упрочнение верхнего слоя свежеуложенного бетона:"],
        "matched_line": "Сухая упрочняющая смесь (топпинг) MasterTop 100 на корундовом заполнителе",
        "context_after": ["Внесение топпинга с расходом 5 кг/м2 с последующей затиркой."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2009,
        "procurement_id": 165102,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Ремонт опор эстакады",
        "category_code": "waterproofing_concrete_repair",
        "category_name": "Гидроизоляция и ремонт бетона",
        "subcategory_code": "concrete_repair",
        "subcategory_name": "Конструкционный ремонт бетона",
        "matched_term": "эмако",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Дефектная_ведомость.xlsx",
        "page_or_sheet": "Лист 1",
        "row_number": 55,
        "context_before": ["Восстановление защитного слоя железобетонных балок:"],
        "matched_line": "Ремонтный состав MasterEmaco S 488 (Эмако) тиксотропного типа для конструкционного ремонта бетона",
        "context_after": ["Толщина нанесения 20-40 мм, прочность на сжатие B45."],
        "expected": "CONFIRMED"
    },
    {
        "detail_id": 2010,
        "procurement_id": 165103,
        "procurement_okpd_code": "41.20.40.000",
        "procurement_okpd_name": "Работы строительные",
        "procurement_title": "Гидроизоляция плоской кровли",
        "category_code": "waterproofing",
        "category_name": "Гидроизоляция",
        "subcategory_code": "bitumen_roll",
        "subcategory_name": "Битумно-полимерные рулонные материалы",
        "matched_term": "техноэласт",
        "match_method": "EXACT",
        "score": 100.0,
        "document_name": "Проект_производства_работ.pdf",
        "page_or_sheet": "6",
        "row_number": 12,
        "context_before": ["Двухслойный гидроизоляционный ковер:"],
        "matched_line": "Наплавляемый битумно-полимерный рулонный материал Техноэласт ЭКП сланец серый",
        "context_after": ["Укладка с нахлестом полотен не менее 100 мм."],
        "expected": "CONFIRMED"
    }
]

results = validator.validate_candidates(positive_canaries)
confirmed = sum(1 for r in results if r["decision"] == "CONFIRMED")
print(f"POSITIVE CONFIRMED: {confirmed}/{len(positive_canaries)}")
for c, r in zip(positive_canaries, results):
    print(f"POS {c['detail_id']} ({c['matched_term']}): Dec={r['decision']}, Conf={r['confidence']}, Reason={r['reason_code']}")
