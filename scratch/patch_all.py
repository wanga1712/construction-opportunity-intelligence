import os

# 1. Reset tracked files from git
os.system("git checkout -- tender_documents_research/document_processor/context_validator.py tender_documents_research/document_processor/context_validator_service.py tests/test_context_validator_semantics_v2.py tests/test_context_validator_v3_trust_boundary.py")

# 2. Modify context_validator.py
with open("tender_documents_research/document_processor/context_validator.py", "r", encoding="utf-8") as f:
    val_text = f.read()

val_text = val_text.replace('VALIDATOR_VERSION = "v3"', 'VALIDATOR_VERSION = "v4"')
val_text = val_text.replace('VALIDATION_METHOD = "QWEN_CONTEXT_V3"', 'VALIDATION_METHOD = "QWEN_CONTEXT_V4"')
val_text = val_text.replace('PROMPT_VERSION = "context_validator_v3"', 'PROMPT_VERSION = "context_validator_v4"')

# We insert the new V4 rules cleanly into SYSTEM_PROMPT
old_sp_rule_3 = """3. UNKNOWN:
Фрагмент контекста действительно недостаточен или неоднозначен для вывода.
Примеры:
- Одиночное общее слово без контекста и параметров.
- Обрезанный или поврежденный фрагмент таблицы/текста, где роль позиции неясна.
- Контекст равновероятно допускает как целевое, так и нецелевое применение.
ВАЖНО: Отсутствие названия бренда или производителя НЕ является причиной для UNKNOWN, если сама позиция/работа четко описана."""

new_sp_rule_3 = """ВАЖНОЕ РАЗЪЯСНЕНИЕ О СЛУЖЕБНЫХ МАРКЕРАХ:
- Текстовые разделители вида "...[контекст до совпадения сокращён]...", "...[контекст после совпадения сокращён]...", "...[строка совпадения сокращена]..." являются СЛУЖЕБНЫМИ СТРУКТУРНЫМИ МАРКЕРАМИ, вставленными системой для соблюдения лимитов длины.
- Служебные маркеры НЕ ЯВЛЯЮТСЯ фактами документа, НЕ являются доказательствами и НЕ должны использоваться как причина для вывода UNKNOWN.
- Принимай решение ИСКЛЮЧИТЕЛЬНО по сохранившемуся дословному тексту документа.

1. CONFIRMED:
Сохранившийся текст документа однозначно подтверждает потребность, закупку, сметную позицию, материал, оборудование или работу целевой подкатегории.
- Документ НЕ ОБЯЗАН содержать дословное название категории или подкатегории (например, подкатегория "уличное освещение" подтверждается позицией "Светильник ДКУ 100 Вт", даже если слова "уличное освещение" отсутствуют).
- Указание бренда, производителя, модели, артикула или ГОСТа НЕ ЯВЛЯЕТСЯ ОБЯЗАТЕЛЬНЫМ.
- Искомый термин (matched_term) указывает на причину отбора фрагмента, но подтверждающим фактом является само описание товара/работы во фрагменте.

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
- Отсутствие бренда, отсутствие дословной фразы подкатегории или наличие служебного маркера сокращения НЕ ЯВЛЯЮТСЯ причинами для UNKNOWN."""

val_text = val_text.replace(old_sp_rule_3, new_sp_rule_3)

# Update question_block
old_qb = """        # Bounded Question Block
        question_block = (
            f"\n[ВОПРОС]\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \"{sub_name_disp}\" (категория \"{cat_name_disp}\", термин \"{term_disp}\" )?\n"
            f"- ВАЖНО: Документальные доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Названия закупки, категории и терминов из раздела метаданных не являются доказательствами.\n"
            f"- Если подкатегория прямо подтверждается спецификацией, позицией ВОР, описанием товара или характеристиками -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата из документа.\n"
            f"- Если созвучие/адрес/название организации/нецелевой товар -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата из документа.\n"
            f"- Если контекст обрезан или совершенно неоднозначен -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\n"
            f"Ответь строго JSON."
        )"""

new_qb = """        # Bounded Question Block
        question_block = (
            f"\n[ВОПРОС]\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \"{sub_name_disp}\" (категория \"{cat_name_disp}\", термин \"{term_disp}\")?\n"
            f"- ВАЖНО: Доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Метаданные заголовка не являются доказательствами.\n"
            f"- Текстовые маркеры вида '...[контекст сокращён]...' являются служебными оформительскими разделителями и НЕ означают неполноту или повреждение доказательств.\n"
            f"- Наличие дословной фразы подкатегории или бренда НЕ требуется: если сохранившийся текст описывает подходящий товар, материал, оборудование или работу -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата.\n"
            f"- Если фрагмент относится к адресу, названию организации, юридическим реквизитам или нецелевому товару -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата.\n"
            f"- 'UNKNOWN' выбирай ТОЛЬКО при реальной фактологической неоднозначности сохранившегося текста -> 'UNKNOWN', confidence: 0.0, supporting_quote: \"\".\n"
            f"Ответь строго JSON."
        )"""

val_text = val_text.replace(old_qb, new_qb)

with open("tender_documents_research/document_processor/context_validator.py", "wb") as f:
    f.write(val_text.encode("utf-8"))

print("context_validator.py updated successfully!")

# 3. Modify context_validator_service.py
with open("tender_documents_research/document_processor/context_validator_service.py", "r", encoding="utf-8") as f:
    svc_text = f.read()

old_trusted = """            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]"""

new_trusted = """            v4_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v4"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V4"
            ]

            v3_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v3"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
            ]"""

svc_text = svc_text.replace(old_trusted, new_trusted, 1)

old_prec = """            if v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3" """

new_prec = """            if v4_trusted:
                target_rows = v4_trusted
                val_ver = "v4"
                val_method = "QWEN_CONTEXT_V4"
            elif v3_trusted:
                target_rows = v3_trusted
                val_ver = "v3"
                val_method = "QWEN_CONTEXT_V3" """

# Also match without trailing space
svc_text = svc_text.replace(
    'if v3_trusted:\n                target_rows = v3_trusted\n                val_ver = "v3"\n                val_method = "QWEN_CONTEXT_V3"',
    'if v4_trusted:\n                target_rows = v4_trusted\n                val_ver = "v4"\n                val_method = "QWEN_CONTEXT_V4"\n            elif v3_trusted:\n                target_rows = v3_trusted\n                val_ver = "v3"\n                val_method = "QWEN_CONTEXT_V3"'
)

with open("tender_documents_research/document_processor/context_validator_service.py", "wb") as f:
    f.write(svc_text.encode("utf-8"))

print("context_validator_service.py updated successfully!")

# 4. Modify test_context_validator_semantics_v2.py
with open("tests/test_context_validator_semantics_v2.py", "r", encoding="utf-8") as f:
    v2_text = f.read()

v2_text = v2_text.replace('assert res["validation_method"] == "QWEN_CONTEXT_V2"', 'assert res["validation_method"] in ("QWEN_CONTEXT_V2", "QWEN_CONTEXT_V4")')
v2_text = v2_text.replace('assert res["validator_version"] == "v2"', 'assert res["validator_version"] in ("v2", "v4")')
v2_text = v2_text.replace('assert res["validator_version"] == VALIDATOR_VERSION == "v2"', 'assert res["validator_version"] == VALIDATOR_VERSION')
v2_text = v2_text.replace('assert res["validation_method"] == VALIDATION_METHOD == "QWEN_CONTEXT_V2"', 'assert res["validation_method"] == VALIDATION_METHOD')

with open("tests/test_context_validator_semantics_v2.py", "wb") as f:
    f.write(v2_text.encode("utf-8"))

print("tests/test_context_validator_semantics_v2.py updated successfully!")

# 5. Modify test_context_validator_v3_trust_boundary.py
with open("tests/test_context_validator_v3_trust_boundary.py", "r", encoding="utf-8") as f:
    v3_text = f.read()

v3_text = v3_text.replace('assert VALIDATOR_VERSION == "v3"', 'assert VALIDATOR_VERSION in ("v3", "v4")')
v3_text = v3_text.replace('assert VALIDATION_METHOD == "QWEN_CONTEXT_V3"', 'assert VALIDATION_METHOD in ("QWEN_CONTEXT_V3", "QWEN_CONTEXT_V4")')
v3_text = v3_text.replace('assert PROMPT_VERSION == "context_validator_v3"', 'assert PROMPT_VERSION in ("context_validator_v3", "context_validator_v4")')

with open("tests/test_context_validator_v3_trust_boundary.py", "wb") as f:
    f.write(v3_text.encode("utf-8"))

print("tests/test_context_validator_v3_trust_boundary.py updated successfully!")
