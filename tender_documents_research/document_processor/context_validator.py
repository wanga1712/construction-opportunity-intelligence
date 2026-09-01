"""Context-based semantic validator for raw document matches.

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

SYSTEM_PROMPT = """Ты — строгий эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов и оборудования.
Твоя задача — проверить, подтверждает ли найденный фрагмент текста документа закупку, потребность, сметную строку, ведомость объемов или спецификацию на материалы/оборудование/работы целевой категории и подкатегории, указанных в блоке [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM].

КРИТЕРИИ:
1. CONFIRMED: Фрагмент документа прямо указывает на закупку целевого материала с указанием конкретной марки, бренда, типа или ГОСТа (например: "ПВХ мембрана Пластфоил", "компаунд Денстоп", "сухая смесь Пенетрон", "смесь MasterTop", "состав MasterEmaco", "материал Техноэласт", "светильник ДКУ", "лоток полимеркомпозитный").
2. REJECTED: Совпадение ложное:
   - Созвучие слов ("ПРОЕКТ" вместо "проспект", "директор" вместо "вектор", "плотность" вместо "плотина").
   - Адрес или город ("ул. Магистральная", "г. Москва").
   - Название организации или должность ("ООО Вектор", "Генеральный директор").
   - Договорная преамбула ("Распоряжением администрации...").
   - Заведомо чужой товар (медицинские шприцы, продукты, канцтовары, спецодежда).
   - Фрагмент содержит стоп-фразу.
3. UNKNOWN: Термин потенциально относится к категории, но в фрагменте нет конкретной марки или контекст обрезан (например: просто "сухая смесь", "покрытие", "пропитка", "мембрана", "состав", "герметик" без марки и без подробных параметров). Поскольку марка не указана, однозначно подтвердить или исключить закупку нельзя -> decision: "UNKNOWN", confidence: 0.0, reason_code: "INSUFFICIENT_CONTEXT".

Ответ СТРОГО JSON:
{
  "detail_id": <int/str>,
  "decision": "CONFIRMED" | "REJECTED" | "UNKNOWN",
  "confidence": <float 0.0-1.0>,
  "supporting_quote": "<дословная цитата или пустая строка для UNKNOWN>",
  "reason_code": "<SPECIFICATION_PRODUCT_REQUIREMENT|FUZZY_LEXICAL_COLLISION|ADDRESS_OR_LOCATION_ONLY|ORGANIZATION_NAME_ONLY|LEGAL_ADMINISTRATIVE_TEXT|UNRELATED_PRODUCT|NEGATIVE_PHRASE_CONTEXT|INSUFFICIENT_CONTEXT>",
  "reason": "<краткое объяснение>"
}"""


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    for ch in ['«', '»', '"', "'", '„', '“', '”']:
        text = text.replace(ch, " ")
    return re.sub(r"\s+", " ", text).strip().lower()


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
    return False


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


def hydrate_candidate_context(candidate: dict) -> dict:
    """Single authority for resolving matched_line, context_before, context_after.

    Precedence for each field:
      A. Explicit non-empty candidate field (from DB column)
      B. Fallback to row_data nested field
      C. For matched_line: also try raw_cells formatting

    Returns a NEW dict with resolved 'matched_line', 'context_before', 'context_after'
    keys added/overwritten. Does NOT mutate the original candidate.
    """
    result = dict(candidate)

    # Parse row_data if needed
    row_data = candidate.get("row_data")
    if isinstance(row_data, str):
        row_data = _safe_parse_json(row_data)
    if not isinstance(row_data, dict):
        row_data = {}

    # --- matched_line ---
    matched_line = candidate.get("matched_line") or ""
    if isinstance(matched_line, str):
        matched_line = matched_line.strip()

    if not matched_line:
        # Fallback B: row_data.matched_line / matched_display_text / text
        matched_line = (
            row_data.get("matched_line")
            or row_data.get("matched_display_text")
            or row_data.get("text")
            or ""
        )
        if isinstance(matched_line, str):
            matched_line = matched_line.strip()

    if not matched_line:
        # Fallback C: format raw_cells as matched text
        matched_line = _format_raw_cells(row_data.get("raw_cells"))

    result["matched_line"] = matched_line

    # --- context_before ---
    db_before = candidate.get("context_before")
    if _is_empty_context(db_before):
        # Fallback to row_data.context_before
        rd_before = row_data.get("context_before")
        if isinstance(rd_before, str):
            rd_before = _safe_parse_json(rd_before)
        if isinstance(rd_before, list) and rd_before:
            result["context_before"] = rd_before
        else:
            result["context_before"] = []
    else:
        # Explicit DB value is non-empty - keep it
        if isinstance(db_before, str):
            db_before = _safe_parse_json(db_before)
        result["context_before"] = db_before if isinstance(db_before, list) else [db_before] if db_before else []

    # --- context_after ---
    db_after = candidate.get("context_after")
    if _is_empty_context(db_after):
        # Fallback to row_data.context_after
        rd_after = row_data.get("context_after")
        if isinstance(rd_after, str):
            rd_after = _safe_parse_json(rd_after)
        if isinstance(rd_after, list) and rd_after:
            result["context_after"] = rd_after
        else:
            result["context_after"] = []
    else:
        # Explicit DB value is non-empty - keep it
        if isinstance(db_after, str):
            db_after = _safe_parse_json(db_after)
        result["context_after"] = db_after if isinstance(db_after, list) else [db_after] if db_after else []

    return result


def _candidate_matched_line(candidate: Dict[str, Any]) -> str:
    """Extracts the best matched text from candidate using hydration precedence."""
    matched_line = candidate.get("matched_line") or ""
    if isinstance(matched_line, str):
        matched_line = matched_line.strip()
    if matched_line:
        return matched_line
    row_data = candidate.get("row_data")
    if isinstance(row_data, str):
        row_data = _safe_parse_json(row_data)
        if not isinstance(row_data, dict):
            row_data = {"matched_line": str(row_data)}
    if isinstance(row_data, dict):
        matched_line = (
            row_data.get("matched_line")
            or row_data.get("matched_display_text")
            or row_data.get("text")
            or ""
        )
        if not matched_line:
            matched_line = _format_raw_cells(row_data.get("raw_cells"))
    return str(matched_line)


class ContextValidator:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        confirm_threshold: float = DEFAULT_CONFIRM_THRESHOLD,
        reject_threshold: float = DEFAULT_REJECT_THRESHOLD,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dedupe: bool = True,
        ai_caller: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.model = model
        self.confirm_threshold = confirm_threshold
        self.reject_threshold = reject_threshold
        self.max_context_chars = max_context_chars
        self.batch_size = batch_size
        self.dedupe = dedupe
        self._ai_caller = ai_caller or (
            lambda p: generate(
                f"{SYSTEM_PROMPT}\n\n{p}",
                model=self.model,
                timeout=75,
                format_json=True,
            )
        )

    def build_context_block(self, candidate: Dict[str, Any]) -> str:
        """Constructs a bounded, informative context block for Qwen."""
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
        method = candidate.get("match_method", "UNKNOWN")

        doc_name = candidate.get("document_name", "")
        page_sheet = candidate.get("page_or_sheet", "")
        row_num = candidate.get("row_number", "")

        before = candidate.get("context_before") or []
        if isinstance(before, str):
            if before.startswith("[") and before.endswith("]"):
                try:
                    before = json.loads(before)
                except Exception:
                    pass
        if isinstance(before, list):
            before_str = "\n".join(str(x) for x in before if x)
        else:
            before_str = str(before)

        after = candidate.get("context_after") or []
        if isinstance(after, str):
            if after.startswith("[") and after.endswith("]"):
                try:
                    after = json.loads(after)
                except Exception:
                    pass
        if isinstance(after, list):
            after_str = "\n".join(str(x) for x in after if x)
        else:
            after_str = str(after)

        matched_line = _candidate_matched_line(candidate)

        neg_phrases = candidate.get("negative_phrases") or []
        neg_str = ", ".join(neg_phrases) if isinstance(neg_phrases, list) else str(neg_phrases)

        doc_loc = f"{page_sheet}:{row_num}" if page_sheet or row_num else ""

        block = (
            f"[ТЕНДЕР]\n"
            f"ID: {pid}\n"
            f"ОКПД2: {okpd_code} ({okpd_name})\n"
            f"Наименование закупки: {p_title}\n\n"
            f"[ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]\n"
            f"Категория: {cat_name} ({cat_code})\n"
            f"Подкатегория: {sub_name} ({sub_code})\n"
            f"Искомый термин: {term}\n"
            f"Документ: {doc_name} {doc_loc}\n\n"
            f"[КОНТЕКСТ ИЗ ДОКУМЕНТА]\n"
            f"{before_str}\n"
            f">>> НАЙДЕННАЯ СТРОКА: {matched_line}\n"
            f"{after_str}\n"
        )
        if neg_str:
            block += f"\n[СТОП-ФРАЗЫ КАТЕГОРИИ]\n{neg_str}\n"

        block += (
            f"\n[ВОПРОС]\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов для подкатегории \"{sub_name}\" (категория \"{cat_name}\", термин \"{term}\")?\n"
            f"- Если прямо указана целевая закупка/спецификация/марка материала -> 'CONFIRMED', confidence: 0.95-1.0, supporting_quote: точная подстрока с товаром.\n"
            f"- Если созвучие/адрес/другой нецелевой товар -> 'REJECTED', confidence: 0.95-1.0, supporting_quote: строка с ложным термином.\n"
            f"- Если контекст обрезан, представляет собой отдельное общее слово или обрывок фразы без конкретной марки и области применения -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\n"
            f"Ответь строго JSON."
        )

        if len(block) > self.max_context_chars:
            block = block[: self.max_context_chars] + "\n...[контекст обрезан]..."

        return block

    def _verify_and_gate_decision(
        self,
        raw_decision: Dict[str, Any],
        candidate: Dict[str, Any],
        context_text: str,
    ) -> Dict[str, Any]:
        """Applies conservative threshold gating, quote verification, and fail-closed defaults."""
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

        # Quote verification: quote must be exact substring in context
        if decision in ("CONFIRMED", "REJECTED") and quote:
            norm_quote = _normalize_whitespace(quote)
            norm_context = _normalize_whitespace(context_text)
            if norm_quote not in norm_context:
                decision = "UNKNOWN"
                reason_code = "HALLUCINATED_QUOTE"
                confidence = 0.0
                reason = f"Supporting quote not found in document context (hallucinated quote): {quote[:60]}"

        # Confidence gating
        if decision == "CONFIRMED" and confidence < self.confirm_threshold:
            decision = "UNKNOWN"
            reason_code = "LOW_CONFIDENCE"
            reason = f"Confidence {confidence:.2f} below CONFIRM_THRESHOLD {self.confirm_threshold:.2f}"
        elif decision == "REJECTED" and confidence < self.reject_threshold:
            decision = "UNKNOWN"
            reason_code = "LOW_CONFIDENCE"
            reason = f"Confidence {confidence:.2f} below REJECT_THRESHOLD {self.reject_threshold:.2f}"

        return {
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
        }

    def validate_single(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Validates a single candidate."""
        context_block = self.build_context_block(candidate)
        prompt = (
            f"Проанализируй совпадение и определи, подтверждает ли оно категорию.\n\n"
            f"{context_block}\n\n"
            f"Верни результат в формате JSON."
        )

        try:
            resp_text = self._ai_caller(prompt)
            # Parse JSON
            match = re.search(r"\{.*\}", resp_text, re.DOTALL)
            if not match:
                raw_decision = {"decision": "UNKNOWN", "reason_code": "INVALID_JSON", "confidence": 0.0}
            else:
                raw_decision = json.loads(match.group(0))
        except Exception as exc:
            logger.warning("Qwen context validator invocation failed: %s", exc)
            raw_decision = {"decision": "UNKNOWN", "reason_code": "MODEL_EXCEPTION", "reason": str(exc), "confidence": 0.0}

        return self._verify_and_gate_decision(raw_decision, candidate, context_block)

    def validate_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validates a batch of candidates, with deduplication if enabled."""
        if not candidates:
            return []

        if not self.dedupe:
            return [self.validate_single(c) for c in candidates]

        # Group by deduplication key
        dedupe_groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
        for c in candidates:
            ctx_text = self.build_context_block(c)
            key = (
                c.get("procurement_id"),
                c.get("document_name"),
                c.get("category_code"),
                c.get("subcategory_code"),
                c.get("matched_term"),
                _normalize_whitespace(ctx_text),
            )
            dedupe_groups.setdefault(key, []).append(c)

        results: List[Dict[str, Any]] = []
        for key, group in dedupe_groups.items():
            rep = group[0]
            rep_result = self.validate_single(rep)

            # Apply result to all members with their own detail_id
            for member in group:
                member_result = dict(rep_result)
                member_result["detail_id"] = member.get("detail_id") or member.get("id")
                results.append(member_result)

        return results


def validate_candidates(
    candidates: List[Dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    ai_caller: Optional[Callable[[str], str]] = None,
    confirm_threshold: float = DEFAULT_CONFIRM_THRESHOLD,
    reject_threshold: float = DEFAULT_REJECT_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Convenience functional entry point."""
    validator = ContextValidator(
        model=model,
        ai_caller=ai_caller,
        confirm_threshold=confirm_threshold,
        reject_threshold=reject_threshold,
    )
    return validator.validate_candidates(candidates)
