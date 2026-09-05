from tender_documents_research.document_processor.context_validator import ContextValidator

prompt_override = """Ты — строгий эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов и оборудования.
Твоя задача — проверить, подтверждает ли найденный фрагмент текста документа закупку, потребность, сметную строку, ведомость объемов или спецификацию на материалы/оборудование/работы целевой категории и подкатегории, указанных в блоке [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM].

КРИТЕРИИ:
1. CONFIRMED: Фрагмент документа прямо указывает на закупку целевого материала с указанием конкретной марки, бренда, типа или ГОСТа (например: "ПВХ мембрана Пластфоил", "компаунд Денстоп", "смесь Пенетрон", "смесь MasterTop", "состав MasterEmaco", "материал Техноэласт", "светильник ДКУ").
2. REJECTED: Совпадение ложное:
   - Созвучие слов ("ПРОЕКТ" вместо "проспект", "директор" вместо "вектор", "плотность" вместо "плотина").
   - Адрес или город ("ул. Магистральная").
   - Название организации или должность ("ООО Вектор", "Генеральный директор").
   - Договорная преамбула ("Распоряжением администрации...").
   - Заведомо чужой товар (медицинские шприцы, продукты, канцтовары).
3. UNKNOWN: Термин потенциально относится к категории, но в фрагменте нет конкретной марки или контекст обрезан (например: просто "сухая смесь", "покрытие", "пропитка", "мембрана", "состав" без марки и без параметров). Поскольку марка не указана, однозначно подтвердить или исключить закупку нельзя -> decision: "UNKNOWN", confidence: 0.0, reason_code: "INSUFFICIENT_CONTEXT".

Ответ СТРОГО JSON:
{
  "detail_id": <int/str>,
  "decision": "CONFIRMED" | "REJECTED" | "UNKNOWN",
  "confidence": <float 0.0-1.0>,
  "supporting_quote": "<дословная цитата или пустая строка для UNKNOWN>",
  "reason_code": "<SPECIFICATION_PRODUCT_REQUIREMENT|FUZZY_LEXICAL_COLLISION|ADDRESS_OR_LOCATION_ONLY|ORGANIZATION_NAME_ONLY|LEGAL_ADMINISTRATIVE_TEXT|UNRELATED_PRODUCT|NEGATIVE_PHRASE_CONTEXT|INSUFFICIENT_CONTEXT>",
  "reason": "<краткое объяснение>"
}"""

from src.services.ai_client import generate
v = ContextValidator(
    ai_caller=lambda p: generate(f"{prompt_override}\n\n{p}", model="qwen2.5:7b", timeout=45, format_json=True)
)

c = {
    'detail_id': 3001,
    'procurement_id': 170001,
    'procurement_okpd_code': '41.20.40.000',
    'procurement_okpd_name': 'Строительные работы',
    'procurement_title': 'Ремонт здания',
    'category_code': 'flooring',
    'category_name': 'Напольные покрытия',
    'subcategory_code': 'dry_shake_topping',
    'subcategory_name': 'Топпинг для бетонных полов',
    'matched_term': 'смесь',
    'document_name': 'Ведомость_материалов.xlsx',
    'context_before': ['[Табличная ячейка без шапки таблицы и марки материала]'],
    'matched_line': 'сухая смесь',
    'context_after': []
}
res = v.validate_single(c)
print("TEST RESULT:", res)
