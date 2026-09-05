import json
from tender_documents_research.document_processor.context_validator import ContextValidator

validator = ContextValidator()
test_candidates = [
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
    }
]

for c in test_candidates:
    ctx = validator.build_context_block(c)
    print("--- PROMPT CONTEXT ---")
    print(ctx)
    res = validator.validate_single(c)
    print("--- RESULT ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))
