"""AI service for the universal procurement opportunity classifier.

The service is deliberately separated from database persistence.  It receives a
small, already-available context packet and the active product taxonomy, asks the
local model for strict JSON, validates the fixed contract and normalises codes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


MODEL_VERSION = "procurement-opportunity-classifier-2026-10-07-7b"
DEFAULT_MODEL = "qwen2.5:7b"

ALLOWED_PROCUREMENT_MODES = frozenset(
    {
        "direct_supply",
        "works_with_products",
        "pure_works",
        "service",
        "unknown",
    }
)
ALLOWED_TAXONOMY_ACTIONS = frozenset({"existing", "propose_new"})

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]|_", re.UNICODE)


def normalize_name(value: Any) -> str:
    """Deterministic name normalisation: lowercase, fold ``ё``, collapse spaces.

    Punctuation is removed as required by the repeat-signature rule.  This helper
    is intentionally independent of database state so tests can reuse it.
    """
    text = str(value or "").lower().replace("ё", "е").strip()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def auto_category_code(parent_name: Any) -> str:
    """Programmatic category code for an auto-discovered taxonomy."""
    digest = hashlib.sha1(normalize_name(parent_name).encode("utf-8")).hexdigest()
    return f"auto_{digest[:10]}"


def auto_subcategory_code(parent_name: Any, subcategory_name: Any) -> str:
    """Programmatic subcategory code for an auto-discovered taxonomy."""
    raw = f"{normalize_name(parent_name)}|{normalize_name(subcategory_name)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"auto_{digest[:10]}"


def build_repeat_signature(
    category_code: Any,
    subcategory_code: Any,
    product_name: Any,
) -> str:
    """Deterministic, non-embedding repeat signature used by the UI."""
    return "|".join(
        [
            str(category_code or "").strip(),
            str(subcategory_code or "").strip(),
            normalize_name(product_name),
        ]
    )


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _confidence(value: Any) -> float:
    number = _number(value)
    if number is None:
        return 0.0
    return max(0.0, min(1.0, number))


def _taxonomy_indexes(
    taxonomy: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_code: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for category in taxonomy or []:
        if not isinstance(category, dict):
            continue
        code = str(category.get("category_code") or "").strip()
        name = normalize_name(category.get("category_name"))
        if code:
            by_code[code] = category
        if name:
            by_name[name] = category
    return by_code, by_name


def _resolve_category(
    raw_code: Any,
    raw_name: Any,
    by_code: Dict[str, Dict[str, Any]],
    by_name: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    code = str(raw_code or "").strip()
    if code and code in by_code:
        return by_code[code]
    name = normalize_name(raw_name)
    if name and name in by_name:
        return by_name[name]
    return None


def _resolve_subcategory(
    category: Dict[str, Any],
    raw_code: Any,
    raw_name: Any,
) -> Optional[Dict[str, Any]]:
    code = str(raw_code or "").strip()
    name = normalize_name(raw_name)
    for sub in category.get("subcategories") or []:
        if not isinstance(sub, dict):
            continue
        if code and str(sub.get("subcategory_code") or "").strip() == code:
            return sub
        if name and normalize_name(sub.get("subcategory_name")) == name:
            return sub
    return None


def build_prompt(context: Dict[str, Any], taxonomy: Sequence[Dict[str, Any]]) -> str:
    """Build the strict-JSON classification prompt."""
    context_block = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
    taxonomy_block = json.dumps(taxonomy, ensure_ascii=False, sort_keys=True, default=str)
    return (
        "Ты классификатор государственных и корпоративных закупок. "
        "Верни ТОЛЬКО строгий JSON без markdown и пояснений.\n\n"
        "Разделяй четыре независимых вопроса:\n"
        "1) что закупают (товарная возможность);\n"
        "2) как закупают (procurement_mode);\n"
        "3) есть ли строительный/инфраструктурный объект;\n"
        "4) что это за объект.\n\n"
        "procurement_mode может быть только: direct_supply, works_with_products, "
        "pure_works, service, unknown.\n"
        "- direct_supply: прямая поставка товаров; object_present обычно false, даже если "
        "заказчик школа/больница/администрация.\n"
        "- works_with_products: работы/реконструкция/ремонт, в составе которых есть товары; "
        "классифицируй и объект, и товары.\n"
        "- pure_works: только работы без товарной возможности.\n"
        "- service: услуги.\n"
        "- unknown: данных недостаточно.\n\n"
        "Одна закупка может дать НЕСКОЛЬКО opportunities. Не выбирай одну главную категорию "
        "и не выбрасывай остальные.\n\n"
        "Активная товарная таксономия (JSON):\n"
        f"{taxonomy_block}\n\n"
        "Правила taxonomy_action:\n"
        "- Если товар подходит хотя бы к одной существующей категории, обязательно "
        "используй existing и её точные category_code/subcategory_code.\n"
        "- propose_new разрешён ТОЛЬКО если подходящей категории действительно нет.\n"
        "- Для существующих категорий НЕ придумывай новые коды. Для новых категорий "
        "category_code/subcategory_code оставь пустыми или произвольными: система заменит их "
        "детерминированными auto-кодами.\n\n"
        "Компьютеры/ноутбуки/серверы/ИТ классифицируются в существующую категорию computers "
        "с её подкатегориями (Ноутбуки, Настольные компьютеры и т.п.). Не создавай "
        "«Компьютеры → Школы/Социальные объекты».\n\n"
        "Объект для works_with_products заполняй по существующей структуре: primary_class, "
        "subcategory, object_type, object_subtype, work_type. Не выдумывай вторую несовместимую "
        "классификацию объектов.\n\n"
        "Контекст закупки (JSON):\n"
        f"{context_block}\n\n"
        "Верни JSON строго по схеме:\n"
        "{\n"
        '  "procurement_mode": "direct_supply|works_with_products|pure_works|service|unknown",\n'
        '  "object_present": false,\n'
        '  "object": {"primary_class": null, "subcategory": null, "object_type": null, '
        '"object_subtype": null, "work_type": null},\n'
        '  "opportunities": [\n'
        '    {\n'
        '      "category_code": "computers",\n'
        '      "category_name": "Компьютерная техника",\n'
        '      "subcategory_code": "laptops",\n'
        '      "subcategory_name": "Ноутбуки",\n'
        '      "product_name": "Ноутбуки",\n'
        '      "quantity": 40,\n'
        '      "unit": "шт",\n'
        '      "taxonomy_action": "existing",\n'
        '      "confidence": 0.94\n'
        "    }\n"
        "  ],\n"
        '  "classification_confidence": 0.94\n'
        "}\n"
    )


def normalize_result(
    raw: Any,
    taxonomy: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate and normalise model output into the fixed service contract."""
    if not isinstance(raw, dict):
        raise ValueError("procurement opportunity model did not return a JSON object")

    mode = str(raw.get("procurement_mode") or "unknown").strip().lower()
    if mode not in ALLOWED_PROCUREMENT_MODES:
        raise ValueError(f"invalid procurement_mode: {mode!r}")

    object_present = bool(raw.get("object_present"))
    if mode == "direct_supply":
        object_present = False

    raw_object = raw.get("object") if isinstance(raw.get("object"), dict) else {}
    object_payload = {
        "primary_class": raw_object.get("primary_class"),
        "subcategory": raw_object.get("subcategory"),
        "object_type": raw_object.get("object_type"),
        "object_subtype": raw_object.get("object_subtype"),
        "work_type": raw_object.get("work_type"),
    }

    by_code, by_name = _taxonomy_indexes(taxonomy)
    opportunities: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    for raw_opp in raw.get("opportunities") or []:
        if not isinstance(raw_opp, dict):
            continue
        opportunity = _normalize_opportunity(raw_opp, by_code, by_name)
        signature = (
            opportunity["category_code"],
            opportunity["subcategory_code"],
            normalize_name(opportunity["product_name"]),
        )
        if signature in seen:
            continue
        seen.add(signature)
        opportunities.append(opportunity)

    return {
        "procurement_mode": mode,
        "object_present": object_present,
        "object": object_payload,
        "opportunities": opportunities,
        "classification_confidence": _confidence(raw.get("classification_confidence")),
    }


def _normalize_opportunity(
    raw: Dict[str, Any],
    by_code: Dict[str, Dict[str, Any]],
    by_name: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    action_raw = str(raw.get("taxonomy_action") or "existing").strip().lower()
    if action_raw not in ALLOWED_TAXONOMY_ACTIONS:
        action_raw = "existing"

    category_code = str(raw.get("category_code") or "").strip()
    category_name = str(raw.get("category_name") or "").strip()
    subcategory_code = str(raw.get("subcategory_code") or "").strip()
    subcategory_name = str(raw.get("subcategory_name") or "").strip()
    product_name = str(raw.get("product_name") or "").strip()

    category = _resolve_category(category_code, category_name, by_code, by_name)
    if action_raw == "existing" and category is None:
        action_raw = "propose_new"

    if action_raw == "existing" and category is not None:
        category_code = str(category.get("category_code") or category_code).strip()
        category_name = str(category.get("category_name") or category_name).strip()
        subcategory = _resolve_subcategory(category, subcategory_code, subcategory_name)
        if subcategory is None:
            # The category exists but the exact subcategory does not.  Treat it as
            # a new subcategory discovery instead of silently inventing a stable code.
            action_raw = "propose_new"
        else:
            subcategory_code = str(
                subcategory.get("subcategory_code") or subcategory_code
            ).strip()
            subcategory_name = str(
                subcategory.get("subcategory_name") or subcategory_name
            ).strip()

    if action_raw == "propose_new":
        category_name = category_name or str(raw.get("category_name") or "").strip()
        subcategory_name = subcategory_name or str(raw.get("subcategory_name") or "").strip()
        product_name = product_name or subcategory_name or category_name
        if not category_name:
            raise ValueError("propose_new opportunity requires category_name")
        category_code = auto_category_code(category_name)
        subcategory_code = auto_subcategory_code(category_name, subcategory_name)

    product_name = product_name or subcategory_name or category_name
    if not product_name:
        raise ValueError("opportunity requires product_name")

    return {
        "category_code": category_code,
        "category_name": category_name,
        "subcategory_code": subcategory_code,
        "subcategory_name": subcategory_name,
        "product_name": product_name,
        "quantity": _number(raw.get("quantity")),
        "unit": str(raw.get("unit") or "").strip() or None,
        "taxonomy_action": action_raw,
        "confidence": _confidence(raw.get("confidence")),
        "repeat_signature": build_repeat_signature(
            category_code, subcategory_code, product_name
        ),
    }


def classify_procurement(
    context: Dict[str, Any],
    taxonomy: Sequence[Dict[str, Any]],
    *,
    model_fn: Optional[Callable[[str], str]] = None,
    timeout: int = 90,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify one procurement and return the validated, normalised result."""
    prompt = build_prompt(context, taxonomy)
    if model_fn is not None:
        text = model_fn(prompt)
    else:
        from src.services.ai_client import extract_json, generate

        resolved_model = model or os.getenv(
            "PROCUREMENT_OPPORTUNITY_MODEL", DEFAULT_MODEL
        )
        text = generate(
            prompt,
            model=resolved_model,
            timeout=timeout,
            format_json=True,
        )
        raw = extract_json(text)
        return normalize_result(raw, taxonomy)

    from src.services.ai_client import extract_json

    raw = extract_json(text)
    return normalize_result(raw, taxonomy)
