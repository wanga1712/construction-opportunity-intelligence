"""Persistent UK contour state and local-AI helpers, without UI dependencies."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from src.services.ai_client import generate
from src.services.waterproofing_ai_context import (
    build_waterproofing_ai_payload,
    build_waterproofing_ai_prompt,
)

CONTOUR_STAGES = [
    "Контур найден",
    "Секретарь / общий телефон найден",
    "Запрошен начальник эксплуатации",
    "Контакт эксплуатации получен",
    "Встреча назначена",
    "Первая встреча проведена",
    "Выбран объект для обследования",
    "Обследование назначено",
    "Обследование проведено",
    "Сделка / ТКП по объекту",
    "Отложено / отказ",
]

FIRST_STEP_OPTIONS = [
    "Позвонить на общий телефон УК и выйти на секретаря или диспетчерскую",
    "Запросить контакт начальника эксплуатации",
    "Назначить короткую встречу с эксплуатацией по портфелю объектов",
    "Отправить письмо с предложением обследования и запросить контакт эксплуатации",
    "Уточнить проблемные помещения: паркинг, подвал, швы, вводы",
]

_STATE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "waterproofing" / "contour_states.jsonl"
)


def contour_key(row: dict[str, Any]) -> str:
    """Return the stable identifier for a management-company contour."""
    return str(
        row.get("uk_ogrn") or row.get("uk_inn") or row.get("uk_id") or row.get("uk_name") or ""
    ).strip()


def load_contour_states() -> dict[str, dict[str, Any]]:
    """Load the newest saved state for every contour."""
    states: dict[str, dict[str, Any]] = {}
    if not _STATE_PATH.exists():
        return states
    for line in _STATE_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(row.get("key") or "")
        if key:
            states[key] = row
    return states


def save_contour_state(key: str, data: dict[str, Any]) -> dict[str, Any]:
    """Append a new immutable contour state record."""
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"key": key, "updated_at": date.today().isoformat(), **data}
    with _STATE_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _candidate_payloads(object_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        build_waterproofing_ai_payload(row)
        for row in sorted(object_rows, key=lambda row: int(row.get("hydro_score") or 0), reverse=True)[:5]
    ]


def contour_ai_payload(
    selected: dict[str, Any], contour_state: dict[str, Any], object_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build safe, compact contour and candidate-object context for AI."""
    return {
        "crm_direction": "Продажи работ и материалов по гидроизоляции",
        "current_stage": contour_state.get("stage"),
        "closed_step_result": contour_state.get("note"),
        "next_action_saved": contour_state.get("next_action"),
        "next_action_date": contour_state.get("next_action_date"),
        "uk": {
            "name": selected.get("uk_name") or contour_state.get("uk_name"),
            "inn": selected.get("uk_inn") or contour_state.get("uk_inn"),
            "ogrn": selected.get("uk_ogrn") or contour_state.get("uk_ogrn"),
            "general_phone": contour_state.get("secretary_phone") or selected.get("uk_phone"),
            "object_count": selected.get("object_count") or contour_state.get("object_count"),
            "ge2_floors": selected.get("ge2_floors") or contour_state.get("ge2_floors"),
        },
        "exploitation_contact_entered_by_user": contour_state.get("exploitation_contact"),
        "candidate_objects": _candidate_payloads(object_rows),
        "task_for_ai": (
            "Подготовь следующий шаг менеджера по этому контуру: кому звонить, что сказать, "
            "какие данные запросить, какой объект упомянуть и когда назначить следующее касание. "
            "Не выдумывай факты; явно укажи недостающие данные."
        ),
    }


def fallback_next_step_script(
    selected: dict[str, Any], contour_state: dict[str, Any], object_rows: list[dict[str, Any]]
) -> str:
    """Provide a usable call script when the local model is unavailable."""
    contact = contour_state.get("exploitation_contact") or "начальника эксплуатации / технический отдел"
    phone = contour_state.get("secretary_phone") or selected.get("uk_phone") or "общий телефон УК"
    top = sorted(object_rows, key=lambda row: int(row.get("hydro_score") or 0), reverse=True)[:1]
    address = (top[0].get("address") if top else None) or "объект из портфеля УК"
    return (
        f"Позвоните по номеру {phone} и попросите соединить с {contact}.\n\n"
        f"Повод для разговора: объект «{address}».\n\n"
        "Скажите: «Добрый день. Мы занимаемся обследованием и ремонтом гидроизоляции "
        "подземных помещений. Подскажите, есть ли в вашем портфеле протечки в паркингах, "
        "подвалах, швах или вводах? Можем провести первичное обследование и подготовить решение».\n\n"
        "Зафиксируйте: ФИО и должность контакта, телефон/email, проблемный объект, тип дефекта, "
        "наличие фото или документов и дату следующего касания."
    )


def ask_contour_ai(
    selected: dict[str, Any], contour_state: dict[str, Any], object_rows: list[dict[str, Any]]
) -> str:
    """Ask the local Ollama model for a Russian contour next-step recommendation."""
    payload = contour_ai_payload(selected, contour_state, object_rows)
    object_prompt = (
        build_waterproofing_ai_prompt(object_rows[0])
        if object_rows
        else "Данные конкретного объекта пока не найдены."
    )
    prompt = (
        "Ты CRM-ассистент по продажам гидроизоляции для управляющих компаний.\n"
        "Сформируй: 1) следующий шаг, 2) скрипт звонка, 3) вопросы эксплуатации, "
        "4) данные для фиксации в CRM. Не выдумывай контакты или дефекты.\n\n"
        f"Контекст контура JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"Контекст приоритетного объекта:\n{object_prompt}"
    )
    try:
        return generate(prompt, timeout=75) or "AI не вернул ответ."
    except Exception as exc:
        return f"AI временно недоступен: {exc}\n\n{fallback_next_step_script(selected, contour_state, object_rows)}"
