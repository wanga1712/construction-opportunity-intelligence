#!/usr/bin/env python3
"""
Directly replaces SYSTEM_PROMPT and question_block in context_validator.py with clean UTF-8.
"""
import os

VAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

with open(VAL_PATH, "rb") as f:
    raw_bytes = f.read()

# Try decoding utf-8
text = raw_bytes.decode("utf-8", errors="ignore")

# Write clean file with valid UTF-8 SYSTEM_PROMPT and constants
clean_code = '''"""Context-based semantic validator for raw document matches.

Decides whether a raw search candidate genuinely supports its immutable source category.

Decisions:
- CONFIRMED: Document context unambiguously specifies a product requirement, material,
             work, or technical specification belonging to the fixed category.
- REJECTED: Candidate is clearly unrelated (fuzzy collision, address, organization name,
            legal boilerplate, unrelated product, negative context).
- UNKNOWN: Context is insufficient or ambiguous, or model confidence is below threshold,
           or supporting quote cannot be verified verbatim in the context.

Absolute rule: VALIDATOR_CAN_RECATEGORIZE = NO.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.services.ai_client import DEFAULT_MODEL, generate

logger = logging.getLogger("document_processor.context_validator")

DEFAULT_CONFIRM_THRESHOLD = 0.80
DEFAULT_REJECT_THRESHOLD = 0.85
DEFAULT_MAX_CONTEXT_CHARS = 3000
DEFAULT_BATCH_SIZE = 10

VALID_DECISIONS = frozenset({"CONFIRMED", "REJECTED", "UNKNOWN"})

VALIDATOR_NAME = "context_validator"
VALIDATOR_VERSION = "v4"
VALIDATION_METHOD = "QWEN_CONTEXT_V4"
PROMPT_VERSION = "context_validator_v4"

SYSTEM_PROMPT = """Ты — эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов, оборудования и работ.
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


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    for ch in ['«', '»', '"', "'", '„', '“', '”']:
        text = text.replace(ch, " ")
    return re.sub(r"\\s+", " ", text).strip().lower()


def _is_empty_context(val) -> bool:
    """Treats None, empty string, whitespace-only, {}, [], '{}', '[]', 'null' as empty."""
    if val is None:
        return True
    if isinstance(val, dict) and not val:
        return True
    if isinstance(val, list) and not val:
        return True
    if isinstance(val, str):
        stripped = val.strip()
        if not stripped or stripped in ('{}', '[]', 'null', 'None'):
            return True
    return True if not val else False


def _safe_parse_json(val):
    """Parse JSON string safely; returns parsed value or original on failure."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _format_raw_cells(raw_cells: list) -> str:
    """Formats raw_cells list into a human-readable table row string.

    Preserves useful factual structure: column text, headers, units, quantities.
    """
    if not raw_cells or not isinstance(raw_cells, list):
        return ""
    parts = []
    for cell in raw_cells:
        if isinstance(cell, dict):
            text = str(cell.get("text", "")).strip()
            if text:
                parts.append(text)
        elif isinstance(cell, str):
            parts.append(cell.strip())
    return " | ".join(parts) if parts else ""


def build_source_document_context(candidate: Dict[str, Any]) -> str:
    """Full hydrated source factual document text (unbounded).

    Contains all context_before, matched_line, and context_after.
    Used for audit and full source inspection.
    """
    c_hydrated = hydrate_candidate_context(candidate)
    before_list = c_hydrated.get("context_before") or []
    after_list = c_hydrated.get("context_after") or []
    m_line = c_hydrated.get("matched_line") or ""

    if isinstance(before_list, str):
        if before_list.startswith("[") and before_list.endswith("]"):
            try: before_list = json.loads(before_list)
            except Exception: pass
    before_str = "\\n".join(str(x) for x in before_list if x) if isinstance(before_list, list) else str(before_list)

    if isinstance(after_list, str):
        if after_list.startswith("[") and after_list.endswith("]"):
            try: after_list = json.loads(after_list)
            except Exception: pass
    after_str = "\\n".join(str(x) for x in after_list if x) if isinstance(after_list, list) else str(after_list)

    parts = []
    if before_str: parts.append(before_str)
    if m_line: parts.append(m_line)
    if after_str: parts.append(after_str)

    return "\\n".join(parts)


def hydrate_candidate_context(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures context_before, context_after, matched_line, and raw_cells are properly parsed.

    Accepts dicts, lists, JSON strings, or raw strings and returns cleaned python types.
    Does NOT modify the input candidate dictionary.
    """
    res = dict(candidate)
    for field in ("context_before", "context_after", "raw_cells"):
        val = res.get(field)
        if isinstance(val, str):
            parsed = _safe_parse_json(val)
            res[field] = parsed

    mline = res.get("matched_line")
    if _is_empty_context(mline):
        cells = res.get("raw_cells")
        formatted = _format_raw_cells(cells)
        if formatted:
            res["matched_line"] = formatted

    return res


def _build_visible_document_context_pair(candidate: Dict[str, Any], max_doc_chars: int) -> Tuple[str, str]:
    """Constructs model-visible document context and pure visible source text.

    Guarantees:
    1. Length of doc_section <= max_doc_chars.
    2. pure_visible_source contains ONLY actual document text (no header or markers).
    3. Structural markers are included in doc_section for model guidance.
    """
    c_hydrated = hydrate_candidate_context(candidate)

    mline_raw = str(c_hydrated.get("matched_line") or "").strip()

    before_raw = c_hydrated.get("context_before") or []
    if isinstance(before_raw, str):
        before_list = [x.strip() for x in before_raw.splitlines() if x.strip()]
    elif isinstance(before_raw, list):
        before_list = [str(x).strip() for x in before_raw if str(x).strip()]
    else:
        before_list = []

    after_raw = c_hydrated.get("context_after") or []
    if isinstance(after_raw, str):
        after_list = [x.strip() for x in after_raw.splitlines() if x.strip()]
    elif isinstance(after_raw, list):
        after_list = [str(x).strip() for x in after_raw if str(x).strip()]
    else:
        after_list = []

    prefix_marker = "...[контекст до совпадения сокращён]...\n"
    suffix_marker = "\n...[контекст после совпадения сокращён]..."
    mline_marker = "...[строка совпадения сокращена]..."

    doc_header_overhead = len("[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n") + len(prefix_marker) + len(suffix_marker) + len(mline_marker) + 10
    if max_doc_chars < doc_header_overhead:
        raise ValueError(f"Impossible document context budget: max_doc_chars={max_doc_chars} is smaller than minimum header overhead {doc_header_overhead}")

    avail_budget = max_doc_chars - doc_header_overhead

    if len(mline_raw) > avail_budget:
        half = avail_budget // 2
        mline_used = mline_raw[:half] + mline_marker + mline_raw[-half:]
        doc_section = f"[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n{mline_used}"
        pure_visible_source = mline_raw
        return doc_section, pure_visible_source

    before_text = "\\n".join(before_list)
    after_text = "\\n".join(after_list)

    remain_for_surrounding = avail_budget - len(mline_raw)
    before_budget = remain_for_surrounding // 2
    after_budget = remain_for_surrounding - before_budget

    used_before = before_text
    before_truncated = False
    if len(before_text) > before_budget:
        used_before = before_text[-before_budget:] if before_budget > 0 else ""
        before_truncated = True

    used_after = after_text
    after_truncated = False
    if len(after_text) > after_budget:
        used_after = after_text[:after_budget] if after_budget > 0 else ""
        after_truncated = True

    if not before_truncated and after_truncated:
        avail_after = remain_for_surrounding - len(before_text)
        if avail_after > len(used_after):
            used_after = after_text[:avail_after] if avail_after > 0 else ""
            after_truncated = len(after_text) > len(used_after)

    elif before_truncated and not after_truncated:
        avail_before = remain_for_surrounding - len(after_text)
        if avail_before > len(used_before):
            used_before = before_text[-avail_before:] if avail_before > 0 else ""
            before_truncated = len(before_text) > len(used_before)

    doc_parts = ["[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n"]
    if used_before:
        if before_truncated:
            doc_parts.append(prefix_marker.strip())
        doc_parts.append(used_before)

    doc_parts.append(f"\\n>>> НАЙДЕННАЯ СТРОКА: \\n{mline_raw}")

    if used_after:
        doc_parts.append(used_after)
        if after_truncated:
            doc_parts.append(suffix_marker.strip())

    doc_section = "\\n".join(doc_parts)

    source_parts = []
    if used_before: source_parts.append(used_before)
    if mline_raw: source_parts.append(mline_raw)
    if used_after: source_parts.append(used_after)

    pure_visible_source = "\\n".join(source_parts)
    return doc_section, pure_visible_source


class ContextValidator:
    """Context-based semantic validator for raw document matches (v4)."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        confirm_threshold: float = DEFAULT_CONFIRM_THRESHOLD,
        reject_threshold: float = DEFAULT_REJECT_THRESHOLD,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        ai_caller: Optional[Callable[[str], str]] = None,
    ):
        self.model = model
        self.confirm_threshold = confirm_threshold
        self.reject_threshold = reject_threshold
        self.max_context_chars = max_context_chars
        self.ai_caller = ai_caller or (
            lambda p: generate(
                f"{SYSTEM_PROMPT}\\n\\n{p}",
                model=self.model,
                timeout=75,
                format_json=True,
            )
        )

    def build_context_payload(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Unified single-execution-path context builder for model prompt AND quote verification."""
        candidate = hydrate_candidate_context(candidate)
        pid = candidate.get("procurement_id", "")
        okpd_code = candidate.get("procurement_okpd_code", "")
        okpd_name = candidate.get("procurement_okpd_name", "")
        p_title = candidate.get("procurement_title", "")

        cat_code = candidate.get("category_code", "")
        cat_name = candidate.get("category_name", cat_code)
        sub_code = candidate.get("subcategory_code", "")
        sub_name = candidate.get("subcategory_name", sub_code)

        term = candidate.get("matched_term", "")
        doc_name = candidate.get("document_name", "")
        page_sheet = candidate.get("page_or_sheet", "")
        row_num = candidate.get("row_number", "")
        doc_loc = f"{page_sheet}:{row_num}" if page_sheet or row_num else ""

        pid_disp = str(pid)[:30]
        okpd_code_disp = str(okpd_code)[:30]
        okpd_name_disp = str(okpd_name)[:30] + "..." if len(str(okpd_name)) > 30 else str(okpd_name)
        p_title_disp = str(p_title)[:40] + "..." if len(str(p_title)) > 40 else str(p_title)

        cat_code_disp = str(cat_code)[:30]
        cat_name_disp = str(cat_name)[:40] + "..." if len(str(cat_name)) > 40 else str(cat_name)
        sub_code_disp = str(sub_code)[:30]
        sub_name_disp = str(sub_name)[:40] + "..." if len(str(sub_name)) > 40 else str(sub_name)

        term_disp = str(term)[:40] + "..." if len(str(term)) > 40 else str(term)
        doc_name_disp = str(doc_name)[:40] + "..." if len(str(doc_name)) > 40 else str(doc_name)
        doc_loc_disp = str(doc_loc)[:30]

        # Bounded Question Block
        question_block = (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name_disp}\\" (категория \\"{cat_name_disp}\\", термин \\"{term_disp}\\")?\\n"
            f"- ВАЖНО: Доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Метаданные заголовка не являются доказательствами.\\n"
            f"- Текстовые маркеры вида '...[контекст сокращён]...' являются служебными оформительскими разделителями и НЕ означают неполноту или повреждение доказательств.\\n"
            f"- Наличие дословной фразы подкатегории или бренда НЕ требуется: если сохранившийся текст описывает подходящий товар, материал, оборудование или работу -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата.\\n"
            f"- Если фрагмент относится к адресу, названию организации, юридическим реквизитам или нецелевому товару -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата.\\n"
            f"- 'UNKNOWN' выбирай ТОЛЬКО при реальной фактологической неоднозначности сохранившегося текста -> 'UNKNOWN', confidence: 0.0, supporting_quote: \\"\\".\\n"
            f"Ответь строго JSON."
        )

        # Bounded Metadata Header
        meta_block = (
            f"[ТЕНДЕР]\\n"
            f"ID: {pid_disp}\\n"
            f"ОКПД2: {okpd_code_disp} ({okpd_name_disp})\\n"
            f"Наименование закупки: {p_title_disp}\\n\\n"
            f"[ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]\\n"
            f"Категория: {cat_name_disp} ({cat_code_disp})\\n"
            f"Подкатегория: {sub_name_disp} ({sub_code_disp})\\n"
            f"Искомый термин: {term_disp}\\n"
            f"Документ: {doc_name_disp} {doc_loc_disp}\\n\\n"
        )

        fixed_overhead = len(meta_block) + len(question_block)
        min_required_budget = fixed_overhead + len("[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n") + 50

        if self.max_context_chars < min_required_budget:
            raise ValueError(f"Impossible context budget: max_context_chars={self.max_context_chars} is smaller than required minimum overhead {min_required_budget}")

        max_doc_budget = self.max_context_chars - fixed_overhead
        doc_section, visible_source_text = _build_visible_document_context_pair(candidate, max_doc_budget)

        context_block = f"{meta_block}{doc_section}{question_block}"

        if len(context_block) > self.max_context_chars:
            overflow = len(context_block) - self.max_context_chars
            doc_section, visible_source_text = _build_visible_document_context_pair(candidate, max_doc_budget - overflow)
            context_block = f"{meta_block}{doc_section}{question_block}"
            if len(context_block) > self.max_context_chars:
                raise ValueError(f"Final context_block length {len(context_block)} exceeds max_context_chars {self.max_context_chars}")

        return {
            "context_block": context_block,
            "visible_doc_section": doc_section,
            "visible_source_text": visible_source_text,
        }

    def build_context_block(self, candidate: Dict[str, Any]) -> str:
        """Constructs a bounded, informative context block for Qwen (backward-compatible wrapper)."""
        payload = self.build_context_payload(candidate)
        return payload["context_block"]

    def _verify_and_gate_decision(
        self,
        raw_decision: Dict[str, Any],
        candidate: Dict[str, Any],
        visible_source_text: str,
    ) -> Dict[str, Any]:
        """Applies conservative threshold gating, quote verification against visible_source_text, and fail-closed defaults."""
        detail_id = candidate.get("detail_id") or candidate.get("id")
        cat_code = candidate.get("category_code")
        sub_code = candidate.get("subcategory_code")

        decision = str(raw_decision.get("decision") or "UNKNOWN").upper().strip()
        if decision not in VALID_DECISIONS:
            decision = "UNKNOWN"
            reason_code = "INVALID_DECISION_ENUM"
        else:
            reason_code = str(raw_decision.get("reason_code") or "UNSPECIFIED")

        try:
            confidence = float(raw_decision.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0

        quote = str(raw_decision.get("supporting_quote") or "").strip()
        reason = str(raw_decision.get("reason") or "").strip()

        raw_decision_val = decision
        raw_confidence = confidence
        raw_reason = reason
        raw_quote = quote

        def _demote(target_decision: str, target_conf: float, rcode: str, msg: str):
            return {
                "detail_id": detail_id,
                "category_code": cat_code,
                "subcategory_code": sub_code,
                "decision": target_decision,
                "confidence": target_conf,
                "supporting_quote": quote if target_decision != "UNKNOWN" else "",
                "reason_code": rcode,
                "reason": f"{reason} | Demoted: {msg}" if reason else f"Demoted: {msg}",
                "validator_name": VALIDATOR_NAME,
                "validator_version": VALIDATOR_VERSION,
                "validation_method": VALIDATION_METHOD,
                "raw_decision": raw_decision_val,
                "raw_confidence": raw_confidence,
                "raw_reason": raw_reason,
                "raw_supporting_quote": raw_quote,
                "raw_model_response": json.dumps(raw_decision, ensure_ascii=False),
                "validated_at": datetime.now(timezone.utc).isoformat(),
            }

        if decision == "CONFIRMED":
            if confidence < self.confirm_threshold:
                return _demote("UNKNOWN", 0.0, "LOW_CONFIDENCE", f"Confidence {confidence:.2f} below confirm_threshold {self.confirm_threshold}")
            if not quote:
                return _demote("UNKNOWN", 0.0, "MISSING_SUPPORTING_QUOTE", "CONFIRMED decision requires explicit non-empty supporting_quote")
            norm_quote = _normalize_whitespace(quote)
            norm_source = _normalize_whitespace(visible_source_text)
            if norm_quote not in norm_source:
                return _demote("UNKNOWN", 0.0, "HALLUCINATED_QUOTE", f"Quote '{quote[:60]}' not found in visible_source_text")

        elif decision == "REJECTED":
            if confidence < self.reject_threshold:
                return _demote("UNKNOWN", 0.0, "LOW_CONFIDENCE", f"Confidence {confidence:.2f} below reject_threshold {self.reject_threshold}")
            if not quote:
                return _demote("UNKNOWN", 0.0, "MISSING_SUPPORTING_QUOTE", "REJECTED decision requires explicit non-empty supporting_quote")
            norm_quote = _normalize_whitespace(quote)
            norm_source = _normalize_whitespace(visible_source_text)
            if norm_quote not in norm_source:
                return _demote("UNKNOWN", 0.0, "HALLUCINATED_QUOTE", f"Quote '{quote[:60]}' not found in visible_source_text")

        else: # UNKNOWN
            confidence = 0.0
            if quote:
                norm_quote = _normalize_whitespace(quote)
                norm_source = _normalize_whitespace(visible_source_text)
                if norm_quote not in norm_source:
                    quote = ""

        return {
            "detail_id": detail_id,
            "category_code": cat_code,
            "subcategory_code": sub_code,
            "decision": decision,
            "confidence": confidence,
            "supporting_quote": quote,
            "reason_code": reason_code,
            "reason": reason,
            "validator_name": VALIDATOR_NAME,
            "validator_version": VALIDATOR_VERSION,
            "validation_method": VALIDATION_METHOD,
            "raw_decision": raw_decision_val,
            "raw_confidence": raw_confidence,
            "raw_reason": raw_reason,
            "raw_supporting_quote": raw_quote,
            "raw_model_response": json.dumps(raw_decision, ensure_ascii=False),
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }

    def validate_single(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Validates a single candidate match."""
        payload = self.build_context_payload(candidate)
        prompt_input = payload["context_block"]
        visible_source_text = payload["visible_source_text"]

        try:
            raw_response_str = self.ai_caller(prompt_input)
        except Exception as exc:
            logger.error("AI client call failed for detail %s: %s", candidate.get("detail_id"), exc)
            return self._verify_and_gate_decision(
                {"decision": "UNKNOWN", "confidence": 0.0, "reason_code": "MODEL_EXCEPTION", "reason": str(exc)},
                candidate,
                visible_source_text,
            )

        try:
            parsed = json.loads(raw_response_str)
            if not isinstance(parsed, dict):
                raise ValueError("Response is not a JSON object")
        except Exception as exc:
            logger.warning("Failed to parse JSON response for detail %s: %s", candidate.get("detail_id"), exc)
            return self._verify_and_gate_decision(
                {"decision": "UNKNOWN", "confidence": 0.0, "reason_code": "INVALID_JSON", "reason": str(exc)},
                candidate,
                visible_source_text,
            )

        return self._verify_and_gate_decision(parsed, candidate, visible_source_text)

    def validate_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validates a batch of candidates using single-execution path."""
        results = []
        for candidate in candidates:
            results.append(self.validate_single(candidate))
        return results
'''

with open(VAL_PATH, "wb") as f:
    f.write(clean_code.encode("utf-8"))

print("Clean UTF-8 context_validator.py written successfully!")
