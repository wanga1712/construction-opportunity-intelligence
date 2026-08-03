"""AI extraction of supplier-ready cards from computer tender TZ text."""
from __future__ import annotations

import os
from typing import Any

from src.services.ai_client import generate_json

MODEL_VERSION = "computer-tz-supplier-card-2026-07-27-7b"
DEFAULT_COMPUTER_TZ_MODEL = "qwen2.5:7b"
MAX_TZ_CHARS = 12000


def build_supplier_card_prompt(
    *,
    auction_name: str,
    okpd_code: str,
    okpd_name: str,
    price: str,
    customer: str,
    tz_text: str,
) -> str:
    excerpt = (tz_text or "").strip()
    if len(excerpt) > MAX_TZ_CHARS:
        excerpt = excerpt[:MAX_TZ_CHARS] + "\n…[обрезано]"
    return (
        "Ты аналитик IT-закупок. По техническому заданию сформируй карточку "
        "для запроса поставщику. Ответь ТОЛЬКО JSON.\n\n"
        "Правила:\n"
        "- Не выдумывай характеристики, которых нет в ТЗ.\n"
        "- Если параметра нет — null или [].\n"
        "- decision: participate | reject | manual_review\n"
        "- equipment_type: notebook|desktop|monoblock|server|mfu|peripheral|mixed|unknown\n\n"
        f"Закупка: {auction_name}\n"
        f"ОКПД: {okpd_code} — {okpd_name}\n"
        f"НМЦК: {price}\n"
        f"Заказчик: {customer}\n\n"
        f"Текст ТЗ / спецификации:\n{excerpt}\n\n"
        "JSON схема:\n"
        "{"
        '"equipment_type":"...",'
        '"decision":"participate|reject|manual_review",'
        '"priority":0,'
        '"qty":null,'
        '"items":[{"category":"notebook|desktop|monoblock|server|mfu|mouse|keyboard|monitor|ups|printer|network|software|other","name":"...","qty":0,"unit":"шт","specs":["..."]}],'
        '"must_have":["характеристика"],'
        '"nice_to_have":["..."],'
        '"red_flags":["ограничитель/ловушка"],'
        '"recommended_config":"кратко для поставщика",'
        '"supplier_request":"готовый текст запроса поставщику",'
        '"questions_to_customer":["..."],'
        '"risk_notes":"...",'
        '"reason":"кратко"'
        "}"
    )


def analyze_tz_to_supplier_card(
    *,
    auction_name: str,
    okpd_code: str = "",
    okpd_name: str = "",
    price: str = "",
    customer: str = "",
    tz_text: str,
    timeout: int = 120,
) -> dict[str, Any]:
    prompt = build_supplier_card_prompt(
        auction_name=auction_name,
        okpd_code=okpd_code,
        okpd_name=okpd_name,
        price=price,
        customer=customer,
        tz_text=tz_text,
    )
    model = os.getenv("COMPUTER_TZ_OLLAMA_MODEL", DEFAULT_COMPUTER_TZ_MODEL)
    data = generate_json(prompt, model=model, timeout=timeout)
    data["model_name"] = model
    data["model_version"] = MODEL_VERSION
    return data
