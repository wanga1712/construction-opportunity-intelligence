"""SECTION_LEVEL_NORMALIZATION_V1 (Phase 4) — model fallback для section-разметки.

Детерминированный детектор (Phase 1/1.5/2A.6) закрывает структурные сметы. Если для
раздела он не дал уверенный контекст (нет меток, сумма `unknown`/`COMPUTED_SUM_UNRELIABLE`),
допускается ОДИН вызов `structured_fact_extractor` (qwen2.5:7b) с жёсткой JSON-схемой:

    {
      "section_name": "…",
      "section_total_raw": "Итого по главе 1 …" | null,
      "section_total_value": 1234.56 | null,
      "children": [
        {"material_name": "…", "quantity": 12.5 | null, "unit": "м3" | null,
         "total_value": 456.78 | null, "source_quote": "…"}
      ]
    }

Fail-closed правила (Phase 4):
  * каждый child ОБЯЗАН иметь `source_quote`, дословно (после нормализации пробелов)
    встречающийся во входном тексте; иначе child отбрасывается;
  * `section_total_value` принимается только при `section_total_raw`, который verifiable,
    и число из raw совпадает со заявленным значением;
  * числа child-а сверяются с его `source_quote`;
  * `DOCUMENT_TOTAL` (листовые «Итого», «Всего с НДС», «Стоимость без НДС», «НДС») в
    section-поля НЕ принимается;
  * если валидных детей нет — результат пустой (модель не «спасает» раздел догадкой).

Scoring / medal / queue / parser этот модуль не трогает.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from tender_documents_research.document_processor.structured_fact_contract import (
    normalize_whitespace,
    parse_numeric_values_from_string,
    verify_source_quote,
)
from tender_documents_research.document_processor.structured_fact_extractor import (
    STRUCTURED_EXTRACTOR_MODEL,
    default_ai_caller,
)

TRUST_STATE = "MANUAL_PROOF_QUARANTINE"
MAX_CHILDREN = 40

_DOC_TOTAL_RE = re.compile(r"^\s*(итого|всего)\b", re.IGNORECASE)
_SECTION_WORD_RE = re.compile(r"(глав|раздел)", re.IGNORECASE)
_NDS_RE = re.compile(r"ндс", re.IGNORECASE)
_COST_RE = re.compile(r"^\s*стоимость\b", re.IGNORECASE)
#: source_quote приходит дампом ячеек ("A=… | B=…"); префикс колонки надо снять.
_CELL_PREFIX_RE = re.compile(r"(^|\|)\s*[A-Z]{1,3}=")
#: одиночные числа внутри цитаты (в т.ч. "200 300", где это НЕ тысячные разряды)
_TOKEN_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _bare_cells(text: str) -> str:
    return _CELL_PREFIX_RE.sub(lambda match: match.group(1) + " ", normalize_whitespace(text))


def prepare_section_text(source_text: str) -> str:
    """Убрать артефакты нашего дампа ячеек перед промптом и проверкой цитат.

    `source_quote` хранится как `A=… | B=…`; разделители `|` и префиксы колонок —
    наше форматирование, а не текст документа. После очистки модель может копировать
    цитаты дословно, а проверка остаётся строгой (verbatim-подстрока).
    """
    lines: List[str] = []
    for line in str(source_text or "").splitlines():
        cleaned = _CELL_PREFIX_RE.sub(lambda match: match.group(1) + " ", line)
        cleaned = re.sub(r"\s*\|\s*", " ", cleaned)
        cleaned = normalize_whitespace(cleaned)
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def build_section_prompt(text: str, *, max_children: int = MAX_CHILDREN) -> str:
    """Жёсткий schema-prompt: только JSON, только цитируемые факты."""
    return (
        "Ты размечаешь РАЗДЕЛ документа (смета/ВОР/спецификация).\n"
        "Верни СТРОГО JSON без пояснений по схеме:\n"
        '{"section_name": str, "section_total_raw": str|null, "section_total_value": number|null,\n'
        ' "children": [{"material_name": str, "quantity": number|null, "unit": str|null,\n'
        '               "total_value": number|null, "source_quote": str}]}\n'
        "Правила:\n"
        f"- максимум {int(max_children)} детей;\n"
        "- у КАЖДОГО child и у section_total_raw обязателен source_quote, ДОСЛОВНО "
        "скопированный из текста ниже;\n"
        "- не придумывай числа: quantity/total_value только те, что есть в source_quote;\n"
        "- если данных для раздела нет — верни {\"children\": []};\n"
        "- НЕ используй как section_total листовые итоги («Итого», «Всего с НДС», "
        "«Стоимость без НДС», «НДС»); допустим только итог главы/раздела;\n"
        "- unit — как в тексте (м3, т, шт, руб. и т.п.).\n"
        "ТЕКСТ:\n" + str(text or "")
    )


def _loads(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    text = str(raw).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        value = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except Exception:
            return None
    return value if isinstance(value, dict) else None


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _number_in_quote(value: Any, quote: str) -> bool:
    """Число допускается только если оно реально присутствует в цитате."""
    number = _as_float(value)
    if number is None:
        return True  # отсутствующее значение допустимо (nullable)
    candidates = set()
    for parsed in parse_numeric_values_from_string(quote or "") or []:
        try:
            candidates.add(float(parsed))
        except (TypeError, ValueError):
            continue
    # Контрактный парсер склеивает "200 300" в 200300 (тысячные разряды), поэтому
    # дополнительно берём числа по одиночным токенам.
    for token in _TOKEN_NUMBER_RE.findall(str(quote or "")):
        try:
            candidates.add(float(token.replace(",", ".")))
        except ValueError:
            continue
    for candidate in candidates:
        if abs(candidate - number) <= max(0.01, abs(number) * 1e-6):
            return True
    return False


def is_document_total(text: str) -> bool:
    """Листовой/документный итог — в section-поля не принимается (Phase 4, п.4)."""
    value = _bare_cells(text)
    if not value:
        return False
    if _NDS_RE.search(value) or _COST_RE.match(value):
        return True
    return bool(_DOC_TOTAL_RE.match(value)) and not _SECTION_WORD_RE.search(value)


def validate_section_payload(
    payload: Optional[Dict[str, Any]], source_text: str
) -> Optional[Dict[str, Any]]:
    """Fail-closed валидация ответа модели. `None` — если разметка не подтверждена."""
    if not isinstance(payload, dict):
        return None
    source_text = prepare_section_text(source_text)
    name = normalize_whitespace(payload.get("section_name") or "")
    if not name:
        return None

    total_raw = normalize_whitespace(payload.get("section_total_raw") or "")
    total_value = _as_float(payload.get("section_total_value"))
    if total_raw and (
        not verify_source_quote(total_raw, source_text)
        or is_document_total(total_raw)
        or not _number_in_quote(total_value, total_raw)
    ):
        total_raw, total_value = "", None

    children: List[Dict[str, Any]] = []
    for raw_child in payload.get("children") or []:
        if not isinstance(raw_child, dict):
            continue
        quote = normalize_whitespace(raw_child.get("source_quote") or "")
        material = normalize_whitespace(raw_child.get("material_name") or "")
        if not quote or not material or not verify_source_quote(quote, source_text):
            continue
        if not _number_in_quote(raw_child.get("quantity"), quote):
            continue
        if not _number_in_quote(raw_child.get("total_value"), quote):
            continue
        children.append({
            "material_name": material,
            "quantity": _as_float(raw_child.get("quantity")),
            "unit": normalize_whitespace(raw_child.get("unit") or "") or None,
            "total_value": _as_float(raw_child.get("total_value")),
            "source_quote": quote,
        })

    if not children:
        return None
    return {
        "section_name": name,
        "section_total_raw": total_raw or None,
        "section_total_value": total_value,
        "section_total_source": "SECTION_TOTAL" if total_value is not None else None,
        "children": children,
        "trust_state": TRUST_STATE,
    }


def extract_sections_with_model(
    text: str,
    *,
    ai_caller: Optional[Callable[..., Tuple[str, Dict[str, Any]]]] = None,
    model: str = STRUCTURED_EXTRACTOR_MODEL,
    max_children: int = MAX_CHILDREN,
) -> Optional[Dict[str, Any]]:
    """Единственный вызов модели с жёсткой схемой; при любой ошибке — `None`."""
    if not str(text or "").strip():
        return None
    text = prepare_section_text(text)
    caller = ai_caller or default_ai_caller
    prompt = build_section_prompt(text, max_children=max_children)
    try:
        raw, _meta = caller(prompt, model=model, format_json=True)
    except Exception:
        return None
    return validate_section_payload(_loads(raw), text)


def section_needs_fallback(total_value: Any, total_source: Any) -> bool:
    """Fallback нужен только там, где детерминированный контекст не уверенный."""
    source = str(total_source or "").strip().upper()
    return source != "SECTION_TOTAL" and (
        source != "COMPUTED_SUM" or total_value is None
    )
