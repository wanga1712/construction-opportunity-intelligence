#!/usr/bin/env python3
"""
Applies R3-4F-E Prompt Semantic Repair to context_validator.py and context_validator_service.py.

Updates:
1. Version constants:
   VALIDATOR_VERSION = "v4"
   VALIDATION_METHOD = "QWEN_CONTEXT_V4"
   PROMPT_VERSION = "context_validator_v4"

2. SYSTEM_PROMPT:
   - Clarifies structural service markers (...[контекст до совпадения сокращён]...) are NOT document facts and NOT evidence for UNKNOWN.
   - Fixes literal subcategory string overconstraint (literal category/subcategory name verbatim is NOT required).
   - Confirms manufacturer/brand/model/GOST are NOT required for CONFIRMED.
   - Matched term is a candidate signal, not proof by itself.
   - Sharpens REJECTED boundary (address/org/legal text -> REJECTED, not UNKNOWN).
   - Sharpens UNKNOWN boundary (reserved strictly for genuine factual ambiguity of remaining visible text).

3. question_block in build_context_payload:
   - Aligns 100% with SYSTEM_PROMPT without ANY contradictions.

4. rebuild_affected_evidence in context_validator_service.py:
   - Adds v4 trusted provenance precedence (v4 > v3 > v2 > v1).
"""

import os

VAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

SVC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

# 1. Update context_validator.py
with open(VAL_PATH, "r", encoding="utf-8") as f:
    val_src = f.read()

# Replace version constants
val_src = val_src.replace('VALIDATOR_VERSION = "v3"', 'VALIDATOR_VERSION = "v4"')
val_src = val_src.replace('VALIDATION_METHOD = "QWEN_CONTEXT_V3"', 'VALIDATION_METHOD = "QWEN_CONTEXT_V4"')
val_src = val_src.replace('PROMPT_VERSION = "context_validator_v3"', 'PROMPT_VERSION = "context_validator_v4"')

new_system_prompt = '''SYSTEM_PROMPT = """Ты — эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов, оборудования и работ.
Твоя задача — проанализировать текст документа и определить, действительно ли закупка или спецификация требует/применяет/содержит товар, материал, оборудование, технологию или работу целевой подкатегории (указанной в блоке [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]).

ВАЖНОЕ РАЗЪЯСНЕНИЕ О СЛУЖЕБНЫХ МАРКЕРАХ:
- Текстовые разделители вида "...[контекст до совпадения сокращён]...", "...[контекст после совпадения сокращён]...", "...[строка совпадения сокращена]..." являются СЛУЖЕБНЫМИ СТРУКТУРНЫМИ МАРКЕРАМИ, вставленными системой для соблюдения лимитов длины.
- Служебные маркеры НЕ ЯВЛЯЮТСЯ фактами документа, НЕ являются доказательствами и НЕ должны использоваться как причина для вывода UNKNOWN.
- Принимай решение ИСКЛЮЧИТЕЛЬНО по сохранившемуся дословному тексту документа.

ПРАВИЛА ПРИНЯТИЯ РЕШЕНИЯ:

1. CONFIRMED:
Сохранившийся текст документа однозначно подтверждает потребность, закупку, сметную позицию, материал, оборудование или работу целевой подкатегории.
- Документ НЕ ОБЯЗАН содержать дословное название категории или подкатегории (например, подкатегория "уличное освещение" подтверждается позицией "Светильник ДКУ 100 Вт", даже если слова "уличное освещение" отсутствуют).
- Указание бренда, производителя, модели, артикула или ГОСТа НЕ ЯВЛЯЕТСЯ ОБЯЗАТЕЛЬНЫМ.
- Искомый термин (matched_term) указывает на причину отбора фрагмента, но подтверждающим фактом является само описание товара/работы во фрагменте.
- Достаточно наименования товара, технических характеристик, позиции спецификации/ВОР, количества с единицами измерения или описания технологического процесса.

2. REJECTED:
Сохранившийся текст документа четко показывает, что совпадение НЕ относится к целевой закупке материалов/работ.
- Для REJECTED НЕ ТРЕБУЕТСЯ наличие конкурирующей спецификации товара.
- Если фрагмент является адресом, местом нахождения, гео-названием -> REJECTED (reason_code: "ADDRESS_OR_LOCATION_ONLY").
- Если фрагмент является наименованием организации, органа власти, реквизитом или ФИО -> REJECTED (reason_code: "ORGANIZATION_NAME_ONLY").
- Если фрагмент является юридическим или административным текстом договора/преамбулы -> REJECTED (reason_code: "LEGAL_ADMINISTRATIVE_TEXT").
- Если фрагмент относится к заведомо нецелевому предмету или лексическому созвучию -> REJECTED (reason_code: "FUZZY_LEXICAL_COLLISION" или "UNRELATED_PRODUCT").

3. UNKNOWN:
Сохранившийся текст документа действительно ФАКТОЛОГИЧЕСКИ НЕОДНОЗНАЧЕН (равновероятно допускает как целевое, так и совершенно иное применение) либо полностью отсутствует предметное описание.
- UNKNOWN НЕ ЯВЛЯЕТСЯ "ответом по умолчанию".
- Отсутствие бренда, отсутствие дословной фразы подкатегории или наличие служебного маркера сокращения НЕ ЯВЛЯЮТСЯ причинами для UNKNOWN.

Формат ответа — СТРОГО JSON:
{
  "detail_id": <int/str>,
  "decision": "CONFIRMED" | "REJECTED" | "UNKNOWN",
  "confidence": <float 0.0-1.0>,
  "supporting_quote": "<дословная цитата из сохранившегося текста документа для CONFIRMED/REJECTED, либо пустая строка>",
  "reason_code": "<SPECIFICATION_PRODUCT_REQUIREMENT|TARGET_WORK_REQUIREMENT|TECHNICAL_TARGET_EVIDENCE|FUZZY_LEXICAL_COLLISION|ADDRESS_OR_LOCATION_ONLY|ORGANIZATION_NAME_ONLY|LEGAL_ADMINISTRATIVE_TEXT|UNRELATED_PRODUCT|INSUFFICIENT_CONTEXT>",
  "reason": "<краткое объяснение>"
}"""'''

p_start = val_src.find('SYSTEM_PROMPT = """')
p_end = val_src.find('def _normalize_whitespace')
assert p_start != -1 and p_end != -1, "Could not locate SYSTEM_PROMPT in context_validator.py"

val_src = val_src[:p_start] + new_system_prompt + "\n\n\n" + val_src[p_end:]

new_question_block = '''        # Bounded Question Block
        question_block = (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name_disp}\\" (категория \\"{cat_name_disp}\\", термин \\"{term_disp}\\")?\\n"
            f"- ВАЖНО: Доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Метаданные заголовка не являются доказательствами.\\n"
            f"- Текстовые маркеры вида '...[контекст сокращён]...' являются служебными оформительскими разделителями и НЕ означают неполноту или повреждение доказательств.\\n"
            f"- Наличие дословной фразы подкатегории или бренда НЕ требуется: если сохранившийся текст описывает подходящий товар, материал, оборудование или работу -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата.\\n"
            f"- Если фрагмент относится к адресу, названию организации, юридическим реквизитам или нецелевому товару -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата.\\n"
            f"- 'UNKNOWN' выбирай ТОЛЬКО при реальной фактологической неоднозначности сохранившегося текста -> 'UNKNOWN', confidence: 0.0, supporting_quote: \\"\\".\\n"
            f"Ответь строго JSON."
        )'''

q_start = val_src.find('# Bounded Question Block')
q_end = val_src.find('# Bounded Metadata Header')
assert q_start != -1 and q_end != -1, "Could not locate question_block in context_validator.py"

val_src = val_src[:q_start] + new_question_block + "\n\n        " + val_src[q_end:]

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Successfully updated context_validator.py to V4 prompt semantics")

# 2. Update context_validator_service.py
with open(SVC_PATH, "r", encoding="utf-8") as f:
    svc_src = f.read()

old_trusted_blocks = '''            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]'''

new_trusted_blocks = '''            v4_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v4"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V4"
            ]

            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]'''

assert old_trusted_blocks in svc_src, "Could not find v3_trusted block in context_validator_service.py"
svc_src = svc_src.replace(old_trusted_blocks, new_trusted_blocks, 1)

old_precedence = '''            if v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3"'''

new_precedence = '''            if v4_trusted:
                target_rows = v4_trusted
                val_ver = "v4"
                val_method = "QWEN_CONTEXT_V4"
            elif v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3"'''

assert old_precedence in svc_src, "Could not find v3_trusted precedence block in context_validator_service.py"
svc_src = svc_src.replace(old_precedence, new_precedence, 1)

with open(SVC_PATH, "w", encoding="utf-8") as f:
    f.write(svc_src)

print("Successfully updated context_validator_service.py to V4 evidence provenance")
