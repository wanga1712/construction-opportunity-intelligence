#!/usr/bin/env python3
"""
Applies R3-4E context validator semantics v2 and provenance updates.
"""
import os

VALIDATOR_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

SERVICE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

# 1. Update context_validator.py
with open(VALIDATOR_PATH, "r", encoding="utf-8") as f:
    v_src = f.read()

# Add v2 version constants
old_constants = '''DEFAULT_CONFIRM_THRESHOLD = 0.80
DEFAULT_REJECT_THRESHOLD = 0.85
DEFAULT_MAX_CONTEXT_CHARS = 3000
DEFAULT_BATCH_SIZE = 10

VALID_DECISIONS = frozenset({"CONFIRMED", "REJECTED", "UNKNOWN"})'''

new_constants = '''DEFAULT_CONFIRM_THRESHOLD = 0.80
DEFAULT_REJECT_THRESHOLD = 0.85
DEFAULT_MAX_CONTEXT_CHARS = 3000
DEFAULT_BATCH_SIZE = 10

VALID_DECISIONS = frozenset({"CONFIRMED", "REJECTED", "UNKNOWN"})

VALIDATOR_NAME = "context_validator"
VALIDATOR_VERSION = "v2"
VALIDATION_METHOD = "QWEN_CONTEXT_V2"
PROMPT_VERSION = "context_validator_v2"'''

assert old_constants in v_src, "old_constants not found"
v_src = v_src.replace(old_constants, new_constants, 1)

# Replace SYSTEM_PROMPT with taxonomy-agnostic v2 prompt
old_prompt_start = 'SYSTEM_PROMPT = """Ты — строгий эксперт-валидатор'
old_prompt_end = '  "reason": "<краткое объяснение>"\n}"""'

prompt_start_idx = v_src.find(old_prompt_start)
prompt_end_idx = v_src.find(old_prompt_end, prompt_start_idx) + len(old_prompt_end)
assert prompt_start_idx != -1 and prompt_end_idx != -1, "SYSTEM_PROMPT bounds not found"

new_system_prompt = '''SYSTEM_PROMPT = """Ты — эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов, оборудования и работ.
Твоя задача — проанализировать контекст документа и определить, действительно ли закупка или спецификация требует/применяет/содержит товар, материал, оборудование, технологию или работу целевой подкатегории (указанной в блоке [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]).

ПРАВИЛА ПРИНЯТИЯ РЕШЕНИЯ:

1. CONFIRMED:
Контекст документа однозначно подтверждает закупку, потребность, сметную позицию, материал, оборудование или работу целевой подкатегории.
- Указание бренда, производителя, модели, артикула или ГОСТа НЕ ЯВЛЯЕТСЯ ОБЯЗАТЕЛЬНЫМ.
- Достаточно явного наименования товара, технических характеристик, позиции спецификации/ведомости объемов работ (ВОР), количества с единицами измерения или описания технологического процесса, относящегося к целевой подкатегории.

2. REJECTED:
Контекст документа четко показывает, что совпадение НЕ относится к целевой подкатегории.
Основные причины:
- Лексическое созвучие (слово похоже по написанию, но означает другой предмет или понятие).
- Адрес или наименование географического объекта.
- Наименование организации, реквизит или должность.
- Юридический или административный текст преамбулы/договора.
- Заведомо нецелевой товар или услуга.
- Явный контекст стоп-фразы подкатегории.

3. UNKNOWN:
Фрагмент контекста действительно недостаточен или неоднозначен для вывода.
Примеры:
- Одиночное общее слово без контекста и параметров.
- Обрезанный или поврежденный фрагмент таблицы/текста, где роль позиции неясна.
- Контекст равновероятно допускает как целевое, так и нецелевое применение.
ВАЖНО: Отсутствие названия бренда или производителя НЕ является причиной для UNKNOWN, если сама позиция/работа четко описана.

Формат ответа — СТРОГО JSON:
{
  "detail_id": <int/str>,
  "decision": "CONFIRMED" | "REJECTED" | "UNKNOWN",
  "confidence": <float 0.0-1.0>,
  "supporting_quote": "<дословная цитата из текста или пустая строка>",
  "reason_code": "<SPECIFICATION_PRODUCT_REQUIREMENT|FUZZY_LEXICAL_COLLISION|ADDRESS_OR_LOCATION_ONLY|ORGANIZATION_NAME_ONLY|LEGAL_ADMINISTRATIVE_TEXT|UNRELATED_PRODUCT|NEGATIVE_PHRASE_CONTEXT|INSUFFICIENT_CONTEXT>",
  "reason": "<краткое объяснение>"
}"""'''

v_src = v_src[:prompt_start_idx] + new_system_prompt + v_src[prompt_end_idx:]

# Replace question prompt at end of build_context_block
old_question = '''        block += (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов для подкатегории \\"{sub_name}\\" (категория \\"{cat_name}\\", термин \\"{term}\\")?\\n"
            f"- Если прямо указана целевая закупка/спецификация/марка материала -> 'CONFIRMED', confidence: 0.95-1.0, supporting_quote: точная подстрока с товаром.\\n"
            f"- Если созвучие/адрес/другой нецелевой товар -> 'REJECTED', confidence: 0.95-1.0, supporting_quote: строка с ложным термином.\\n"
            f"- Если контекст обрезан, представляет собой отдельное общее слово или обрывок фразы без конкретной марки и области применения -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\\n"
            f"Ответь строго JSON."
        )'''

new_question = '''        block += (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name}\\" (категория \\"{cat_name}\\", термин \\"{term}\\")?\\n"
            f"- Если подкатегория прямо подтверждается спецификацией, позицией ВОР, описанием товара или характеристиками -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: дословная цитата.\\n"
            f"- Если созвучие/адрес/название организации/нецелевой товар -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: дословная цитата.\\n"
            f"- Если контекст обрезан или совершенно неоднозначен -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\\n"
            f"Ответь строго JSON."
        )'''

assert old_question in v_src, "old_question block not found"
v_src = v_src.replace(old_question, new_question, 1)

# Update return dict in _verify_and_gate_decision to use v2 constants
old_return_dict = '''        return {
            "detail_id": detail_id,
            "procurement_id": candidate.get("procurement_id"),
            "category_code": cat_code,  # IMMUTABLE
            "subcategory_code": sub_code,  # IMMUTABLE
            "decision": decision,
            "confidence": confidence,
            "supporting_quote": quote,
            "reason_code": reason_code,
            "reason": reason,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "validator_name": "context_validator",
            "validator_version": "v1",
            "validation_method": "QWEN_CONTEXT_V1",
        }'''

new_return_dict = '''        return {
            "detail_id": detail_id,
            "procurement_id": candidate.get("procurement_id"),
            "category_code": cat_code,  # IMMUTABLE
            "subcategory_code": sub_code,  # IMMUTABLE
            "decision": decision,
            "confidence": confidence,
            "supporting_quote": quote,
            "reason_code": reason_code,
            "reason": reason,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "validator_name": VALIDATOR_NAME,
            "validator_version": VALIDATOR_VERSION,
            "validation_method": VALIDATION_METHOD,
        }'''

assert old_return_dict in v_src, "old_return_dict not found"
v_src = v_src.replace(old_return_dict, new_return_dict, 1)

with open(VALIDATOR_PATH, "w", encoding="utf-8") as f:
    f.write(v_src)

print("Updated context_validator.py with v2 semantics and provenance.")

# 2. Update context_validator_service.py for v2 evidence rebuilding
with open(SERVICE_PATH, "r", encoding="utf-8") as f:
    s_src = f.read()

old_rebuild = '''def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
    """Rebuilds document_evidence ONLY for affected procurement/category pairs."""
    if not affected:
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected:
            cur.execute("""
                SELECT d.score, m.queue_id
                FROM document_match_details d
                JOIN document_matches m ON d.match_id = m.id
                WHERE d.procurement_id = %s
                  AND d.category_code = %s
                  AND d.pipeline_generation = %s
                  AND d.validation_status = 'CONFIRMED'
            """, (pid, cat, PIPELINE_GENERATION))
            confirmed_rows = cur.fetchall()

            if confirmed_rows:
                max_score = max(float(r["score"]) for r in confirmed_rows)
                match_count = len(confirmed_rows)
                queue_id = confirmed_rows[0]["queue_id"]

                cur.execute("""
                    INSERT INTO document_evidence
                    (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (procurement_id, category_code, pipeline_generation)
                    DO UPDATE SET
                        evidence_score = EXCLUDED.evidence_score,
                        match_count = EXCLUDED.match_count,
                        validation_status = 'CONFIRMED',
                        validation_version = 'v1',
                        validation_method = 'QWEN_CONTEXT_V1'
                """, (
                    pid, queue_id, cat, max_score, match_count,
                    "STRUCTURED_EXTRACTION_PENDING", "CONFIRMED", "v1", "QWEN_CONTEXT_V1",
                    PIPELINE_GENERATION
                ))'''

new_rebuild = '''def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
    """Rebuilds document_evidence ONLY for affected procurement/category pairs.

    Truthful version provenance: if any confirmed row in the group was validated with v2,
    the resulting evidence record uses validation_version='v2', validation_method='QWEN_CONTEXT_V2'.
    Otherwise if only legacy v1 confirmed rows exist, retains 'v1', 'QWEN_CONTEXT_V1'.
    """
    if not affected:
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected:
            cur.execute("""
                SELECT d.score, m.queue_id, d.validator_version, d.validation_method
                FROM document_match_details d
                JOIN document_matches m ON d.match_id = m.id
                WHERE d.procurement_id = %s
                  AND d.category_code = %s
                  AND d.pipeline_generation = %s
                  AND d.validation_status = 'CONFIRMED'
            """, (pid, cat, PIPELINE_GENERATION))
            confirmed_rows = cur.fetchall()

            if confirmed_rows:
                max_score = max(float(r["score"]) for r in confirmed_rows)
                match_count = len(confirmed_rows)
                queue_id = confirmed_rows[0]["queue_id"]

                has_v2 = any(
                    str(r.get("validator_version") or "").lower() == "v2"
                    or "V2" in str(r.get("validation_method") or "").upper()
                    for r in confirmed_rows
                )
                val_ver = "v2" if has_v2 else "v1"
                val_method = "QWEN_CONTEXT_V2" if has_v2 else "QWEN_CONTEXT_V1"

                cur.execute("""
                    INSERT INTO document_evidence
                    (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (procurement_id, category_code, pipeline_generation)
                    DO UPDATE SET
                        evidence_score = EXCLUDED.evidence_score,
                        match_count = EXCLUDED.match_count,
                        validation_status = 'CONFIRMED',
                        validation_version = EXCLUDED.validation_version,
                        validation_method = EXCLUDED.validation_method
                """, (
                    pid, queue_id, cat, max_score, match_count,
                    "STRUCTURED_EXTRACTION_PENDING", "CONFIRMED", val_ver, val_method,
                    PIPELINE_GENERATION
                ))'''

assert old_rebuild in s_src, "old_rebuild in context_validator_service.py not found"
s_src = s_src.replace(old_rebuild, new_rebuild, 1)

with open(SERVICE_PATH, "w", encoding="utf-8") as f:
    f.write(s_src)

print("Updated context_validator_service.py for truthful v2 evidence provenance.")
