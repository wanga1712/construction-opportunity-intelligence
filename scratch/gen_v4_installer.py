import os

sys_prompt_raw = """Ты — эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов, оборудования и работ.
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
}"""

q_block_raw = """        # Bounded Question Block
        question_block = (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name_disp}\\" (категория \\"{cat_name_disp}\\", термин \\"{term_disp}\\")?\\n"
            f"- ВАЖНО: Доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Метаданные заголовка не являются доказательствами.\\n"
            f"- Текстовые маркеры вида '...[контекст сокращён]...' являются служебными оформительскими разделителями и НЕ означают неполноту или повреждение доказательств.\\n"
            f"- Наличие дословной фразы подкатегории или бренда НЕ требуется: если сохранившийся текст описывает подходящий товар, материал, оборудование или работу -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата.\\n"
            f"- Если фрагмент относится к адресу, названию организации, юридическим реквизитам или нецелевому товару -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата.\\n"
            f"- 'UNKNOWN' выбирай ТОЛЬКО при реальной фактологической неоднозначности сохранившегося текста -> 'UNKNOWN', confidence: 0.0, supporting_quote: \\"\\".\\n"
            f"Ответь строго JSON."
        )"""

# Convert to escaped ascii strings
sys_escaped = sys_prompt_raw.encode("unicode-escape").decode("ascii")
q_escaped = q_block_raw.encode("unicode-escape").decode("ascii")

script_content = f"""# -*- coding: utf-8 -*-
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VAL_PATH = os.path.join(REPO_ROOT, "tender_documents_research", "document_processor", "context_validator.py")
SVC_PATH = os.path.join(REPO_ROOT, "tender_documents_research", "document_processor", "context_validator_service.py")
V2_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_semantics_v2.py")
V3_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_v3_trust_boundary.py")
V4_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_v4_decision_boundary.py")

os.system(f"git checkout -- {{VAL_PATH}} {{SVC_PATH}} {{V2_TEST_PATH}} {{V3_TEST_PATH}}")

sys_prompt_text = "{sys_escaped}".encode("ascii").decode("unicode-escape")
q_block_text = "{q_escaped}".encode("ascii").decode("unicode-escape")

with open(VAL_PATH, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace('VALIDATOR_VERSION = "v3"', 'VALIDATOR_VERSION = "v4"')
text = text.replace('VALIDATION_METHOD = "QWEN_CONTEXT_V3"', 'VALIDATION_METHOD = "QWEN_CONTEXT_V4"')
text = text.replace('PROMPT_VERSION = "context_validator_v3"', 'PROMPT_VERSION = "context_validator_v4"')

sys_start = text.find('SYSTEM_PROMPT = """')
sys_end = text.find('def _normalize_whitespace')
assert sys_start != -1 and sys_end != -1
text = text[:sys_start] + "SYSTEM_PROMPT = \\"\\"\\"" + sys_prompt_text + "\\\"\\\"\\"" + text[sys_end:]

q_start = text.find('# Bounded Question Block')
q_end = text.find('# Bounded Metadata Header')
assert q_start != -1 and q_end != -1
text = text[:q_start] + q_block_text + "\\n\\n        " + text[q_end:]

with open(VAL_PATH, "wb") as f:
    f.write(text.encode("utf-8"))

print("1. context_validator.py updated cleanly.")

# Service
with open(SVC_PATH, "rb") as f:
    svc_data = f.read()

old_trusted = b'''            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]'''

new_trusted = b'''            v4_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v4"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V4"
            ]

            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]'''

svc_data = svc_data.replace(old_trusted, new_trusted, 1)

old_prec = b'''            if v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3"'''

new_prec = b'''            if v4_trusted:
                target_rows = v4_trusted
                val_ver = "v4"
                val_method = "QWEN_CONTEXT_V4"
            elif v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3"'''

svc_data = svc_data.replace(old_prec, new_prec, 1)

with open(SVC_PATH, "wb") as f:
    f.write(svc_data)

print("2. context_validator_service.py updated.")

# V2 Test
with open(V2_TEST_PATH, "rb") as f:
    v2_data = f.read()

v2_data = v2_data.replace(b'assert res["validation_method"] == "QWEN_CONTEXT_V2"', b'assert res["validation_method"] in ("QWEN_CONTEXT_V2", "QWEN_CONTEXT_V4")')
v2_data = v2_data.replace(b'assert res["validator_version"] == "v2"', b'assert res["validator_version"] in ("v2", "v4")')
v2_data = v2_data.replace(b'assert res["validator_version"] == VALIDATOR_VERSION == "v2"', b'assert res["validator_version"] == VALIDATOR_VERSION')
v2_data = v2_data.replace(b'assert res["validation_method"] == VALIDATION_METHOD == "QWEN_CONTEXT_V2"', b'assert res["validation_method"] == VALIDATION_METHOD')

with open(V2_TEST_PATH, "wb") as f:
    f.write(v2_data)

print("3. test_context_validator_semantics_v2.py updated.")

# V3 Test
with open(V3_TEST_PATH, "rb") as f:
    v3_data = f.read()

v3_data = v3_data.replace(b'assert VALIDATOR_VERSION == "v3"', b'assert VALIDATOR_VERSION in ("v3", "v4")')
v3_data = v3_data.replace(b'assert VALIDATION_METHOD == "QWEN_CONTEXT_V3"', b'assert VALIDATION_METHOD in ("QWEN_CONTEXT_V3", "QWEN_CONTEXT_V4")')
v3_data = v3_data.replace(b'assert PROMPT_VERSION == "context_validator_v3"', b'assert PROMPT_VERSION in ("context_validator_v3", "context_validator_v4")')

with open(V3_TEST_PATH, "wb") as f:
    f.write(v3_data)

print("4. test_context_validator_v3_trust_boundary.py updated.")
"""

with open("scratch/apply_v4_clean.py", "w", encoding="ascii") as f:
    f.write(script_content)

print("Generated scratch/apply_v4_clean.py in 100% ASCII!")
