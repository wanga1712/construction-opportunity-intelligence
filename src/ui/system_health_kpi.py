"""KPI ribbon (SLDS cards) and collector stats for the system health page."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src.services.system_health_config import HOST_S13, HOST_S7
from src.ui import system_health_slds as slds
from src.ui.system_health_alerts_view import legacy_device
from src.ui.system_health_format import SERVICE_LABELS_RU, fmt_load, fmt_pct

def kpi_ribbon(hosts: Dict[str, Any], snap: Dict[str, Any]) -> None:
    s13 = hosts.get(HOST_S13) or {}
    s7 = hosts.get(HOST_S7) or {}
    s13_cpu = (s13.get("cpu") or {}).get("usage_pct")
    s7_cpu = (s7.get("cpu") or {}).get("usage_pct")
    cards = [
        slds.kpi_card(
            "Server 13 · CPU load",
            fmt_pct(s13_cpu),
            sub=fmt_load(s13.get("cpu") or {}),
            tone=slds.cpu_tone(s13_cpu),
            value_tone=True,
            badges=cpu_badge(s13_cpu),
        ),
        slds.kpi_card(
            "Server 7 · CPU load",
            fmt_pct(s7_cpu),
            sub=fmt_load(s7.get("cpu") or {}),
            tone=slds.cpu_tone(s7_cpu),
            value_tone=True,
            badges=cpu_badge(s7_cpu),
        ),
        storage_kpi(s13),
        collectors_kpi(s7),
    ]
    columns = st.columns(4, gap="medium")
    for column, html in zip(columns, cards):
        column.markdown(html, unsafe_allow_html=True)


def cpu_badge(pct: Optional[float]) -> str:
    tone = slds.cpu_tone(pct)
    if tone == "crit":
        return slds.badge("Critical / Spike", "crit")
    if tone == "warn":
        return slds.badge("High", "warn")
    return slds.badge("Норма", "neutral")


def storage_kpi(host: Dict[str, Any]) -> str:
    legacy = legacy_device(host)
    alerts = host.get("alerts") or []
    devices = {
        a.get("device_or_service")
        for a in alerts
        if a.get("source") in ("disk", "smart") and a.get("level") in ("WARNING", "CRITICAL")
    }
    real = sorted(d for d in devices if d and d != legacy)
    total_warn = len(real) + (1 if legacy else 0)
    value = f"{total_warn} Warning" if total_warn else "Норма"
    parts = [f"предупреждения: {', '.join(real)}"] if real else []
    if legacy:
        parts.append(f"{legacy} — UNUSED LEGACY NTFS, legacy / не используется, non-blocking")
    if legacy:
        badges = slds.badge("UNUSED LEGACY NTFS", "neutral") + slds.badge("низкий приоритет", "neutral")
    else:
        badges = slds.badge("Без замечаний", "ok")
    return slds.kpi_card(
        "Storage Health (S13)",
        value,
        sub=" · ".join(parts) or "физические диски без замечаний",
        tone="warn" if real else ("neutral" if legacy else "ok"),
        value_tone=bool(real),
        badges=badges,
    )


def collectors_stats(host: Dict[str, Any]) -> Tuple[int, int, List[Dict[str, Any]]]:
    collectors = host.get("source_collectors") or []
    summary = host.get("source_collectors_summary") or {}
    total = int(summary.get("total") or len(collectors))
    if summary.get("ok") is not None:
        ok = int(summary.get("ok"))
    else:
        ok = sum(1 for c in collectors if (c.get("ui_status") or "OK") == "OK")
    failing = [c for c in collectors if (c.get("ui_status") or "OK") != "OK"]
    if not failing and summary.get("failing_units"):
        failing = [{"unit": unit} for unit in summary.get("failing_units") or []]
    return ok, total, failing


def collector_name(collector: Dict[str, Any]) -> str:
    unit = collector.get("unit") or collector.get("name") or "?"
    return SERVICE_LABELS_RU.get(unit, unit)


def collectors_kpi(host: Dict[str, Any]) -> str:
    ok, total, failing = collectors_stats(host)
    if not total:
        return slds.kpi_card("Data Collectors (S7)", "—", sub="нет данных коллекторов", tone="neutral")
    down = len(failing)
    sub = f"{down} collector down: {', '.join(collector_name(c) for c in failing)}" if down else "все коллекторы активны"
    badges = slds.badge("Warning", "warn") if down else slds.badge("Operational", "ok")
    return slds.kpi_card("Data Collectors (S7)", f"{ok} / {total}", sub=sub, tone="warn" if down else "ok", badges=badges)
