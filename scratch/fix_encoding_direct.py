#!/usr/bin/env python3
"""
Directly updates context_validator.py, test_context_validator_v4_decision_boundary.py,
and test_context_validator_semantics_v2.py with clean UTF-8 encoding.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VAL_PATH = os.path.join(REPO_ROOT, "tender_documents_research", "document_processor", "context_validator.py")
V4_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_v4_decision_boundary.py")
V2_TEST_PATH = os.path.join(REPO_ROOT, "tests", "test_context_validator_semantics_v2.py")

# 1. Update context_validator.py in clean UTF-8
with open(VAL_PATH, "r", encoding="utf-8", errors="replace") as f:
    val_text = f.read()

val_text = val_text.replace('VALIDATOR_VERSION = "v3"', 'VALIDATOR_VERSION = "v4"')
val_text = val_text.replace('VALIDATION_METHOD = "QWEN_CONTEXT_V3"', 'VALIDATION_METHOD = "QWEN_CONTEXT_V4"')
val_text = val_text.replace('PROMPT_VERSION = "context_validator_v3"', 'PROMPT_VERSION = "context_validator_v4"')

sys_prompt_clean = '''SYSTEM_PROMPT = """Ты — эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов, оборудования и работ.
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

q_block_clean = '''        # Bounded Question Block
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

# Replace SYSTEM_PROMPT block
s_idx = val_text.find('SYSTEM_PROMPT = """')
e_idx = val_text.find('def _normalize_whitespace')
if s_idx != -1 and e_idx != -1:
    val_text = val_text[:s_idx] + sys_prompt_clean + "\n\n\n" + val_text[e_idx:]

# Replace question_block
qs_idx = val_text.find('# Bounded Question Block')
qe_idx = val_text.find('# Bounded Metadata Header')
if qs_idx != -1 and qe_idx != -1:
    val_text = val_text[:qs_idx] + q_block_clean + "\n\n        " + val_text[qe_idx:]

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_text)

print("Updated context_validator.py in clean UTF-8.")

# 2. Update test_context_validator_semantics_v2.py
with open(V2_TEST_PATH, "r", encoding="utf-8", errors="replace") as f:
    v2_text = f.read()

v2_text = v2_text.replace('assert res["validation_method"] == "QWEN_CONTEXT_V2"', 'assert res["validation_method"] == VALIDATION_METHOD')
v2_text = v2_text.replace('assert res["validator_version"] == "v2"', 'assert res["validator_version"] == VALIDATOR_VERSION')

with open(V2_TEST_PATH, "w", encoding="utf-8") as f:
    f.write(v2_text)

print("Updated test_context_validator_semantics_v2.py in clean UTF-8.")

# 3. Write test_context_validator_v4_decision_boundary.py in clean UTF-8
v4_test_code = '''"""Deterministic unit tests for ContextValidator V4 Decision Boundary Prompt Repair (R3-4F-E).

Validates:
1. V4 versioning constants (VALIDATOR_VERSION="v4", VALIDATION_METHOD="QWEN_CONTEXT_V4", PROMPT_VERSION="context_validator_v4")
2. Prompt contract rules (truncation markers != UNKNOWN, literal subcategory not required, brand/model not required, address/org/legal -> REJECTED)
3. Mocked decision contract tests (CONFIRMED, REJECTED, UNKNOWN, quote gating, fail-closed demotions)
4. Strict V4 evidence provenance isolation in rebuild_affected_evidence()
"""

import pytest
import sys
import os
import json
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)
from tender_documents_research.document_processor.context_validator_service import (
    rebuild_affected_evidence,
)


class MockCursor:
    def __init__(self, fetch_data=None):
        self.fetch_data = fetch_data or []
        self.last_query = ""
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params

    def fetchall(self):
        return self.fetch_data


class MockConnection:
    def __init__(self, fetch_data=None):
        self.cursor_obj = MockCursor(fetch_data)

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def commit(self):
        pass


# 1. Versioning check
def test_v4_versioning_constants():
    assert VALIDATOR_NAME == "context_validator"
    assert VALIDATOR_VERSION == "v4"
    assert VALIDATION_METHOD == "QWEN_CONTEXT_V4"
    assert PROMPT_VERSION == "context_validator_v4"


# 2. Prompt Contract Tests (Section 16)
def test_prompt_contract_truncation_markers_not_automatic_unknown():
    assert "НЕ должны использоваться как причина для вывода UNKNOWN" in SYSTEM_PROMPT
    assert "СЛУЖЕБНЫМИ СТРУКТУРНЫМИ МАРКЕРАМИ" in SYSTEM_PROMPT


def test_prompt_contract_literal_subcategory_not_required():
    assert "НЕ ОБЯЗАНО содержать дословное название категории или подкатегории" in SYSTEM_PROMPT


def test_prompt_contract_brand_model_not_required():
    assert "Указание бренда, производителя, модели, артикула или ГОСТа НЕ ЯВЛЯЕТСЯ ОБЯЗАТЕЛЬНЫМ" in SYSTEM_PROMPT


def test_prompt_contract_address_org_legal_rejected():
    assert "ADDRESS_OR_LOCATION_ONLY" in SYSTEM_PROMPT
    assert "ORGANIZATION_NAME_ONLY" in SYSTEM_PROMPT
    assert "LEGAL_ADMINISTRATIVE_TEXT" in SYSTEM_PROMPT


def test_prompt_question_block_consistency():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "road_street",
        "subcategory_name": "Уличное освещение",
        "matched_term": "светильник",
        "matched_line": "Светильник ДКУ 100 Вт.",
    }
    payload = validator.build_context_payload(candidate)
    block = payload["context_block"]

    assert "[ВОПРОС]" in block
    assert "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" in block
    assert "НЕ означают неполноту или повреждение доказательств" in block
    assert "Наличие дословной фразы подкатегории или бренда НЕ требуется" in block
    assert "адресу, названию организации, юридическим реквизитам" in block


# 3. Mocked Decision Contract Tests (Section 17)
def test_mocked_confirmed_with_valid_quote():
    candidate = {
        "detail_id": 201,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 201,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Светильник уличный ДКУ 100 Вт.",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Уличный светильник ДКУ",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "CONFIRMED"
    assert res["confidence"] == 0.95
    assert res["validator_version"] == "v4"
    assert res["validation_method"] == "QWEN_CONTEXT_V4"
    assert res["supporting_quote"] == "Светильник уличный ДКУ 100 Вт."


def test_mocked_rejected_with_valid_quote():
    candidate = {
        "detail_id": 202,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "управлен",
        "matched_line": "Адрес: г. Москва, ул. Большая Тульская, д. 9, Управа района.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 202,
            "decision": "REJECTED",
            "confidence": 0.90,
            "supporting_quote": "Управа района",
            "reason_code": "ORGANIZATION_NAME_ONLY",
            "reason": "Наименование органа власти",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "REJECTED"
    assert res["confidence"] == 0.90
    assert res["supporting_quote"] == "Управа района"
    assert res["reason_code"] == "ORGANIZATION_NAME_ONLY"


def test_mocked_unknown_decision():
    candidate = {
        "detail_id": 203,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "вектор",
        "matched_line": "Заместитель директора А.А. Захаров.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 203,
            "decision": "UNKNOWN",
            "confidence": 0.0,
            "supporting_quote": "",
            "reason_code": "INSUFFICIENT_CONTEXT",
            "reason": "Контекст не содержит спецификации",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["confidence"] == 0.0


def test_mocked_confirmed_missing_quote_demoted():
    candidate = {
        "detail_id": 204,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 204,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "",
            "reason": "No quote provided",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "MISSING_SUPPORTING_QUOTE"


def test_mocked_rejected_hallucinated_quote_demoted():
    candidate = {
        "detail_id": 205,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 205,
            "decision": "REJECTED",
            "confidence": 0.90,
            "supporting_quote": "Выдуманная цитата которой нет в документе",
            "reason": "Hallucinated quote",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "HALLUCINATED_QUOTE"


# 4. Strict V4 Evidence Provenance
def test_strict_v4_evidence_provenance():
    mock_conn = MockConnection()

    mock_conn.cursor_obj.fetch_data = [
        {"score": 95.0, "queue_id": 1, "validator_version": "v4", "validation_method": "QWEN_CONTEXT_V4"},
        {"score": 90.0, "queue_id": 1, "validator_version": "v3", "validation_method": "QWEN_CONTEXT_V3"},
        {"score": 85.0, "queue_id": 1, "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"},
    ]
    rebuild_affected_evidence(mock_conn, {(100, "lighting")})
    query = mock_conn.cursor_obj.last_query
    assert "INSERT INTO document_evidence" in query
    params = mock_conn.cursor_obj.last_params
    assert params[7] == "v4"  # validator_version
    assert params[8] == "QWEN_CONTEXT_V4"  # validation_method
'''

with open(V4_TEST_PATH, "w", encoding="utf-8") as f:
    f.write(v4_test_code)

print("Wrote test_context_validator_v4_decision_boundary.py in clean UTF-8.")
