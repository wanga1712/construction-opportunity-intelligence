"""Consolidated (deduplicated) alerts widget for the system health page."""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import streamlit as st

from src.ui import system_health_slds as slds
from src.ui.system_health_format import fmt_ts_local
from src.ui.system_health_sections import section_title

_ALERT_TEXTS = {
    "disk health WARNING": "Физическое состояние диска: предупреждение (SMART PASSED не равен полностью исправен)",
    "disk health CRITICAL": "Физическое состояние диска: критично",
    "pending sectors > 0": "Нестабильные (pending) сектора",
    "reallocated sectors > 0": "Переназначенные (reallocated) сектора",
    "sustained CPU >=90%": "Устойчивая загрузка CPU >= 90%",
    "source collector not active": "Коллектор источника не активен",
    "disk used warning": "Заполнение тома выше порога",
    "disk used critical": "Заполнение тома критично",
    "CPU temperature warning": "Температура CPU выше порога",
    "CPU temperature critical": "Температура CPU критична",
    "host unreachable / collection failed": "Сервер недоступен / сбор метрик не удался",
    "PostgreSQL not healthy": "PostgreSQL не отвечает",
    "CRM Streamlit not healthy": "CRM Streamlit не отвечает",
}


def legacy_device(host: Dict[str, Any]) -> str:
    role = host.get("sdb_role") or {}
    if role.get("IS_SDB_CURRENTLY_UNUSED"):
        return role.get("device") or "/dev/sdb"
    return ""


def group_alerts(alerts: Sequence[Dict[str, Any]]) -> List[Tuple[Tuple[str, str], List[Dict[str, Any]]]]:
    """One group per (host, device_or_service) — several warnings collapse into one card."""
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for alert in alerts:
        if alert.get("level") not in ("WARNING", "CRITICAL"):
            continue
        key = (alert.get("host_id") or "?", alert.get("device_or_service") or "?")
        groups.setdefault(key, []).append(alert)
    return sorted(
        groups.items(),
        key=lambda item: (0 if any(a.get("level") == "CRITICAL" for a in item[1]) else 1, item[0][0], item[0][1]),
    )


def alert_line(alert: Dict[str, Any]) -> str:
    message = alert.get("message") or ""
    text = _ALERT_TEXTS.get(message, message)
    observed, threshold = alert.get("observed"), alert.get("threshold")
    tail = f" · факт {observed} / порог {threshold}" if observed is not None or threshold is not None else ""
    return slds.esc(f"{text}{tail}")


def alert_meta(items: Sequence[Dict[str, Any]]) -> str:
    first = min((i.get("first_seen") or "") for i in items)
    last = max((i.get("last_seen") or "") for i in items)
    sources = ", ".join(sorted({(i.get("source") or "?") for i in items}))
    return f"источник: {sources} · впервые {fmt_ts_local(first)} · последний раз {fmt_ts_local(last)}"


def device_detail(host: Dict[str, Any], device: str) -> List[Tuple[str, Any]]:
    rows: List[Tuple[str, Any]] = []
    for disk in host.get("disk_health") or []:
        if disk.get("device") != device:
            continue
        rows = [
            ("Модель", disk.get("model") or "—"),
            ("SMART overall", f"{disk.get('overall') or '—'} · статус {disk.get('status') or '—'}"),
            ("Температура", f"{disk.get('temperature_c')} °C" if disk.get("temperature_c") is not None else "—"),
            ("Pending sectors", disk.get("pending_sectors")),
            ("Reallocated sectors", disk.get("reallocated_sectors")),
            ("CRC errors", disk.get("crc_errors")),
            ("Power-on hours", disk.get("power_on_hours")),
        ]
        wear = disk.get("wear") or {}
        if wear.get("percent_used_estimate") is not None:
            rows.append(("Износ (оценка)", f"{wear.get('percent_used_estimate')}%"))
        break
    role = host.get("sdb_role") or {}
    if role.get("IS_SDB_CURRENTLY_UNUSED") and role.get("device") == device:
        rows.append(("Роль", f"{role.get('SDB_DATA_ROLE')} — не используется CRM / PostgreSQL / document storage"))
    return rows


def render_consolidated_alerts(alerts: Sequence[Dict[str, Any]], hosts: Dict[str, Any], title: str = "Инциденты и предупреждения") -> None:
    st.markdown(section_title(title), unsafe_allow_html=True)
    groups = group_alerts(alerts)
    if not groups:
        st.markdown(slds.card("Предупреждений нет", '<div class="slds-empty">Все отслеживаемые узлы в норме.</div>'), unsafe_allow_html=True)
        return
    for (host_id, target), items in groups:
        level = "CRITICAL" if any(i.get("level") == "CRITICAL" for i in items) else "WARNING"
        tone = "crit" if level == "CRITICAL" else "warn"
        host = hosts.get(host_id) or {}
        role = next((str(i.get("device_role")) for i in items if i.get("device_role")), "")
        downgraded = any(i.get("priority") == "LOW" or i.get("non_blocking") for i in items)
        legacy = downgraded or (bool(legacy_device(host)) and legacy_device(host) == target)
        badges = slds.status_badge(level)
        if legacy:
            badges += slds.badge((role or "UNUSED LEGACY NTFS").replace("_", " "), "neutral")
            badges += slds.badge("низкий приоритет", "neutral")
        if len(items) > 1:
            badges += slds.badge(f"{len(items)} сигнала", "info")
        card_title = f"{host_id}: Диск {target} требует внимания" if str(target).startswith("/dev/") else f"{host_id}: {target}"
        st.markdown(
            slds.alert_card(card_title, tone=tone, badges=badges, lines=[alert_line(i) for i in items], meta=alert_meta(items)),
            unsafe_allow_html=True,
        )
        detail = device_detail(host, target)
        if detail or len(items) > 1:
            with st.expander(f"Детали · {target}"):
                if detail:
                    st.markdown(
                        "".join(
                            f'<div class="slds-svc"><span class="slds-svc__note">{slds.esc(k)}</span>'
                            f'<span class="slds-svc__name">{slds.esc(v)}</span></div>'
                            for k, v in detail
                        ),
                        unsafe_allow_html=True,
                    )
                for item in items:
                    st.caption(f"{item.get('source')} · {item.get('message')} · наблюдалось {item.get('observed')}")
