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

DEFAULT_CONFIRM_THRESHOLD = 0.90
DEFAULT_REJECT_THRESHOLD = 0.85
DEFAULT_MAX_CONTEXT_CHARS = 3000
DEFAULT_BATCH_SIZE = 10

VALID_DECISIONS = frozenset({"CONFIRMED", "REJECTED", "UNKNOWN"})

SYSTEM_PROMPT = """Ты — строгий эксперт-валидатор совпадений в документах госзакупок для CRM строительных материалов и оборудования.
Твоя задача — проверить, подтверждает ли найденный фрагмент текста документа закупку, потребность, сметную строку, ведомость объемов или спецификацию на материалы/оборудование/работы целевой категории и подкатегории, указанных в блоке [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM].

ВНИМАНИЕ:
- Целевая проверка проводится строго на соответствие блоку [ЦЕЛЕВАЯ КАТЕГОРИЯ CRM] (Категория и Подкатегория)!
- Менять категорию или подкатегорию ЗАПРЕЩЕНО.
- Наименование закупки в блоке [ТЕНДЕР] — это лишь общее название всего тендера, а не фильтр. Не путай название тендера с категорией товара!

КРИТЕРИИ ПРИНЯТИЯ РЕШЕНИЯ (decision):
1. CONFIRMED: Фрагмент документа прямо указывает на закупку, смету, ведомость объемов, ТЗ или применение целевого материала/оборудования указанной категории/подкатегории. ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ ДЛЯ CONFIRMED: указана конкретная марка, бренд, ГОСТ, химический тип или точная техническая спецификация (например: "ПВХ мембрана Пластфоил", "компаунд Денстоп ЭП-201", "сухая смесь Пенетрон", "смесь MasterTop 100", "состав MasterEmaco S 488", "материал Техноэласт ЭКП", "светильник ДКУ-100", "лоток полимеркомпозитный").
2. REJECTED: Совпадение очевидно ложное:
   - FUZZY_LEXICAL_COLLISION: созвучие слов ("ПРОЕКТ" вместо "проспект", "директор" вместо "вектор", "плотность" вместо "плотина").
   - ADDRESS_OR_LOCATION_ONLY: адрес, улица, город ("просп. Ленина", "ул. 3-я Магистральная").
   - ORGANIZATION_NAME_ONLY: наименование организации, должность ("ООО Вектор", "Генеральный директор").
   - LEGAL_ADMINISTRATIVE_TEXT: распоряжение, преамбула, типовой договор ("Распоряжением администрации...").
   - UNRELATED_PRODUCT: совершенно другой товар (медицинские шприцы/иглы для гидроизоляции, канцтовары, продукты, спецодежда).
   - NEGATIVE_PHRASE_CONTEXT: фрагмент содержит стоп-фразу.
3. UNKNOWN: Фрагмент содержит лишь общее родовое слово или обрезанную строку без указания конкретной марки, типа материала или точной спецификации (например: просто "мембрана", "покрытие", "пропитка", "состав", "герметик", "смесь" без марки и без подробных параметров). Поскольку марка и тип материала не указаны, невозможно однозначно подтвердить закупку целевого продукта -> decision: "UNKNOWN", confidence: 0.0, reason_code: "INSUFFICIENT_CONTEXT"."""�есто "вектор", "плотность" вместо "плотина").
   - ADDRESS_OR_LOCATION_ONLY: адрес, улица, город ("просп. Ленина", "ул. 3-я Магистральная").
   - ORGANIZATION_NAME_ONLY: наименование организации, должность ("ООО Вектор", "Генеральный директор").
   - LEGAL_ADMINISTRATIVE_TEXT: распоряжение, преамбула, типовой договор ("Распоряжением администрации...").
   - UNRELATED_PRODUCT: совершенно другой товар (медицинские шприцы/иглы для гидроизоляции, канцтовары, продукты, спецодежда).
   - NEGATIVE_PHRASE_CONTEXT: фрагмент содержит стоп-фразу.
3. UNKNOWN: Фрагмент поврежден, сильно обрезан, представляет собой неполный обрывок фразы или табличную ячейку без контекста (например, просто "герметик", "покрытие", "пропитка", "мембрана", "состав" без характеристик и области применения). Невозможно подтвердить конкретную закупку или исключить её -> decision: "UNKNOWN", confidence: 0.0-0.5, reason_code: "INSUFFICIENT_CONTEXT".

Правила:
- confidence: степень уверенности в решении (0.95-1.0 если уверен, <0.90 если сомневаешься).
- supporting_quote: точная дословная цитата (подстрока) из блока [КОНТЕКСТ ИЗ ДОКУМЕНТА].
  * Для CONFIRMED: строка/фраза с товаром/материалом.
  * Для REJECTED: строка с ложным термином.
  * Для UNKNOWN: пустая строка "".

Ответ СТРОГО в формате JSON без markdown:
{
  "detail_id": <int/str>,
  "decision": "CONFIRMED" | "REJECTED" | "UNKNOWN",
  "confidence": <float 0.0-1.0>,
  "supporting_quote": "<дословная цитата из контекста>",
  "reason_code": "<SPECIFICATION_PRODUCT_REQUIREMENT|FUZZY_LEXICAL_COLLISION|ADDRESS_OR_LOCATION_ONLY|ORGANIZATION_NAME_ONLY|LEGAL_ADMINISTRATIVE_TEXT|UNRELATED_PRODUCT|NEGATIVE_PHRASE_CONTEXT|INSUFFICIENT_CONTEXT>",
  "reason": "<краткое объяснение>"
}"""


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[«»\"'„“”]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


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

        matched_line = candidate.get("matched_line") or ""
        row_data = candidate.get("row_data")
        if isinstance(row_data, str):
            try:
                row_data = json.loads(row_data)
            except Exception:
                row_data = {"matched_line": row_data}
        if not matched_line and isinstance(row_data, dict):
            matched_line = (
                row_data.get("matched_line")
                or row_data.get("matched_display_text")
                or row_data.get("text")
                or ""
            )

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
            f"Подтверждает ли данный фрагмент документа реальную закупку, смету, ведомость объемов или ТЗ на товар/материал/работу для подкатегории \"{sub_name}\" (категория \"{cat_name}\", термин \"{term}\")?\n"
            f"- Если ДА -> decision: 'CONFIRMED', confidence: 0.95-1.0, supporting_quote: точная подстрока с товаром.\n"
            f"- Если НЕТ (ложное созвучие слов, адрес, должность/организация, типовой договор, другой товар) -> decision: 'REJECTED', confidence: 0.95-1.0, supporting_quote: строка с ложным термином.\n"
            f"- Если неясно / контекст обрезан / недостаточно данных -> decision: 'UNKNOWN'.\n"
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
