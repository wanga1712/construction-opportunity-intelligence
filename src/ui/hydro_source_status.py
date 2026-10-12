"""Статус ночного синка Hydro: время, объём, SUCCESS/FAILED.

Используется и в карточках паркингов, и на дашборде состояния системы.
Ошибка загрузки всегда видна снаружи — молчаливого «ноль записей» нет.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.ui import system_health_slds as slds

STALE_AFTER_HOURS = 36
SOURCE = "NSPD_PARKING"
SOURCE_TITLE = "Гидроизоляция: загрузка NSPD (паркинги и УК)"
EMPTY_MESSAGE = "Загрузка Hydro ещё не запускалась: нет записи в crm_hydro_source_health."


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def describe(health: Mapping[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Единая трактовка статуса: свежесть, тон, человекочитаемая подпись."""
    health = dict(health or {})
    moment = now or datetime.now(timezone.utc)
    status = str(health.get("status") or "").upper()
    last_success = _parse(health.get("last_success_at"))
    last_attempt = _parse(health.get("last_attempt_at"))
    age_hours = None
    if last_success:
        age_hours = (moment - last_success).total_seconds() / 3600.0
    if not status:
        return {"state": "never_run", "tone": "neutral", "label": "Нет данных",
                "age_hours": None, "message": EMPTY_MESSAGE, "health": health}
    if status == "FAILED":
        return {"state": "failed", "tone": "crit", "label": "FAILED",
                "age_hours": age_hours,
                "message": str(health.get("safe_error_message") or "Причина не записана"),
                "error_class": str(health.get("safe_error_class") or ""),
                "health": health}
    if age_hours is not None and age_hours > STALE_AFTER_HOURS:
        return {"state": "stale", "tone": "warn", "label": "SUCCESS (устарел)",
                "age_hours": age_hours,
                "message": f"Последняя успешная загрузка была {age_hours:.0f} ч назад.",
                "health": health}
    return {"state": "ok", "tone": "ok", "label": "SUCCESS", "age_hours": age_hours,
            "message": "", "health": health}


def ribbon(view: Mapping[str, Any]) -> str:
    """SLDS-лента: статус + время синка + объём загруженного."""
    health = view.get("health") or {}
    loaded = health.get("rows_seen")
    items = [
        ("Статус синка", view.get("label")),
        ("Последний синк", slds.esc(slds_and_time(health.get("last_attempt_at")))),
        ("Успешный синк", slds.esc(slds_and_time(health.get("last_success_at")))),
        ("Загружено записей", slds.esc("—" if loaded is None else f"{int(loaded):,}".replace(",", " "))),
    ]
    body = "".join(
        f'<div class="slds-ribbon__item"><span class="slds-label">{slds.esc(label)}</span>'
        f'<span class="slds-ribbon__val">{value}</span></div>'
        for label, value in items
    )
    tone_badge = slds.badge(view.get("label") or "—", str(view.get("tone") or "neutral"))
    return f'<div class="slds-ribbon">{body}<div class="slds-ribbon__item">{tone_badge}</div></div>'


def slds_and_time(value: Any) -> str:
    moment = _parse(value)
    if not moment:
        return "—"
    return moment.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def alert(view: Mapping[str, Any]) -> tuple[str, str] | None:
    """(tone, текст) для предупреждения, либо None если всё в порядке."""
    state = view.get("state")
    if state == "ok":
        return None
    if state == "never_run":
        return ("warn", EMPTY_MESSAGE)
    if state == "failed":
        suffix = f" ({view.get('error_class')})" if view.get("error_class") else ""
        return ("crit", f"Загрузка Hydro упала{suffix}: {view.get('message')}")
    return ("warn", str(view.get("message") or "Данные загрузки устарели."))


def status_tile(crm_db: Any) -> dict[str, Any]:
    """Готовый срез для дашборда состояния системы: без БД-исключений наружу."""
    from src.services.hydro.card_repository import HydroCardRepository

    view = describe(HydroCardRepository(crm_db).source_health())
    health = view.get("health") or {}
    view["rows_loaded"] = health.get("rows_seen")
    return view