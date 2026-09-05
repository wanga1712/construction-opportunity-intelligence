import json
from tender_documents_research.document_processor.context_validator import ContextValidator

validator = ContextValidator(confirm_threshold=0.85, reject_threshold=0.90)
emaco_candidate = {
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
    "matched_line": "Ремонтный состав MasterEmaco S 488 тиксотропного типа для конструкционного ремонта",
    "context_after": ["Толщина нанесения 20-40 мм, прочность на сжатие B45."],
}

ctx = validator.build_context_block(emaco_candidate)
print("--- PROMPT CONTEXT ---")
print(ctx)
res = validator.validate_single(emaco_candidate)
print("--- RESULT ---")
print(json.dumps(res, indent=2, ensure_ascii=False))
