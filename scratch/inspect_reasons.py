import json
from tender_documents_research.document_processor.context_validator import ContextValidator

validator = ContextValidator()
test_candidates = [
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
        "document_name": "Ведомость_работ.xlsx",
        "context_before": ["Устройство финишного полимерного покрытия пола в производственном помещении."],
        "matched_line": "Нанесение самонивелирующегося эпоксидного компаунда Денстоп ЭП-201 толщиной 2.5 мм",
        "context_after": ["Расход материала 3.2 кг/м2."]
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
        "document_name": "Спецификация_материалов.pdf",
        "context_before": ["Материалы для гидроизоляции чаши:"],
        "matched_line": "Кровельная ПВХ мембрана Пластфоил F1.5 толщиной 1.5 мм",
        "context_after": ["Монтаж методом сварки горячим воздухом."]
    }
]

for c in test_candidates:
    ctx = validator.build_context_block(c)
    print("--- PROMPT CONTEXT ---")
    print(ctx)
    res = validator.validate_single(c)
    print("--- RESULT ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))
