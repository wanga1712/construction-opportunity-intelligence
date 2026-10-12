"""Streamlit: Состояние серверов — SLDS-дашборд (snapshot-only)."""
from __future__ import annotations

import html
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from src.services.system_health_config import (
    HISTORY_LOADED_ON_OVERVIEW,
    HOST_S13,
    HOST_S7,
    PAGE_LABEL,
    S7_SSH_CALLS_ON_UI_RERUN,
    SYSTEM_HEALTH_MUTATING_ACTIONS,
    UI_HARDWARE_PROBES,
    UI_REFRESH_SEC,
)
from src.services.system_health_read import load_dashboard
from src.ui import system_health_slds as slds
from src.ui.system_health_alerts_view import legacy_device, render_consolidated_alerts
from src.ui.system_health_format import (
    SERVICE_LABELS_RU,
    disk_summary_ru,
    fmt_age,
    fmt_bytes,
    fmt_load,
    fmt_pct,
    fmt_temp,
    fmt_ts_local,
    fmt_uptime,
    status_ru,
)
from src.ui.system_health_kpi import collectors_stats, collector_name, kpi_ribbon
from src.ui.hydro_source_status import alert as hydro_alert
from src.ui.hydro_source_status import describe as hydro_describe
from src.ui.hydro_source_status import SOURCE_TITLE as hydro_source_title
from src.ui.hydro_source_status import ribbon as hydro_ribbon
from src.ui.system_health_sections import (
    cpu_cell_style,
    proc_label,
    proc_status,
    render_collectors_table,
    render_disk_table,
    render_disks_section,
    render_history_charts,
    render_network_section,
    render_processes_section,
    render_processes_table,
    render_services_section,
    render_services_table,
    section_title,
)

assert UI_HARDWARE_PROBES == 0
assert SYSTEM_HEALTH_MUTATING_ACTIONS == 0
assert S7_SSH_CALLS_ON_UI_RERUN == 0
assert HISTORY_LOADED_ON_OVERVIEW is False

_SECTIONS = [
    "ОБЗОР",
    "SERVER 13",
    "SERVER 7",
    "Диски",
    "Нагрузка",
    "Сервисы",
    "Сеть",
    "Процессы",
    "Предупреждения",
]
_HISTORY_SECTIONS = ("SERVER 13", "SERVER 7", "Нагрузка")
_HOST_OF_SECTION = {"SERVER 13": HOST_S13, "SERVER 7": HOST_S7}
_TITLE_OF_HOST = {HOST_S13: "SERVER 13", HOST_S7: "SERVER 7"}
_HEALTH_SERVICE_UNITS = (
    "crm-v3-shadow-predictor.service",
    "crm-v3-autonomous-worker.service",
    "crm-v3-learning-dataset.service",
    "crm-system-health-collector.service",
    "tender-docs-daemon.service",
)
@st.cache_resource(show_spinner=False)
def _crm_db_conn() -> Any:
    """Отдельное подключение к CRM БД: статус синка Hydro живёт там, не в снимке."""
    try:
        from src.services.db_bootstrap import connect_crm_database

        return connect_crm_database()
    except Exception:  # noqa: BLE001 - панель состояния обязана работать и без CRM
        return None


@st.cache_data(ttl=60, show_spinner=False)
def _hydro_sync_view() -> Dict[str, Any]:
    from src.services.hydro.card_repository import HydroCardRepository

    return hydro_describe(HydroCardRepository(_crm_db_conn()).source_health())


def _render_hydro_sync() -> None:
    """Статус ночного загрузчика гидроизоляции: время, объём, SUCCESS/FAILED."""
    try:
        view = _hydro_sync_view()
    except Exception as error:  # noqa: BLE001
        st.warning(f"Статус синка Hydro недоступен: {error}")
        return
    st.markdown(
        f'<div class="slds-label">{html.escape(hydro_source_title)}</div>'
        f'{hydro_ribbon(view)}',
        unsafe_allow_html=True,
    )
    notice = hydro_alert(view)
    if notice:
        (st.error if notice[0] == "crit" else st.warning)(notice[1])


def render_system_health_page(_service=None) -> None:
    st.markdown(slds.SLDS_CSS, unsafe_allow_html=True)

    @st.fragment(run_every=timedelta(seconds=UI_REFRESH_SEC))
    def _live() -> None:
        snap_view = load_dashboard()
        _cluster_ribbon(snap_view.get("snapshot") or {}, snap_view)
        _render_hydro_sync()
        if not snap_view.get("ready"):
            st.warning(snap_view.get("message") or "Collector down")
            return

        section = st.radio(
            "Раздел",
            _SECTIONS,
            horizontal=True,
            key="sys_health_view",
            label_visibility="collapsed",
        )
        need_hist = section in _HISTORY_SECTIONS
        host_key = _HOST_OF_SECTION.get(section)
        if section == "Нагрузка":
            host_key = st.radio(
                "Хост для графиков",
                [HOST_S13, HOST_S7],
                horizontal=True,
                key="shm_load_host",
            )
        hours = 1.0
        if need_hist:
            range_label = st.radio(
                "Период графиков",
                ["1 час", "6 часов", "24 часа"],
                horizontal=True,
                key="shm_range",
            )
            hours = {"1 час": 1.0, "6 часов": 6.0, "24 часа": 24.0}[range_label]

        if need_hist:
            view = load_dashboard(include_history=need_hist, history_host=host_key, history_hours=hours)
        else:
            view = snap_view
        assert view.get("hardware_probes") == 0
        assert view.get("s7_ssh_calls") == 0
        if not need_hist:
            assert view.get("history_loaded") is False

        snap = view.get("snapshot") or {}
        hosts = snap.get("hosts") or {}
        history = view.get("history") or []

        # selected section → build selected detail only (other sections stay lazy)
        if section == "ОБЗОР":
            _render_overview(hosts, snap)
        elif section in _HOST_OF_SECTION:
            _render_host_detail(hosts.get(host_key) or {}, _TITLE_OF_HOST[host_key], history, host_key)
        elif section == "Диски":
            render_disks_section(hosts)
        elif section == "Нагрузка":
            _render_load_section(hosts.get(host_key or HOST_S13) or {}, history, host_key or HOST_S13)
        elif section == "Сервисы":
            render_services_section(hosts)
        elif section == "Сеть":
            render_network_section(hosts)
        elif section == "Процессы":
            render_processes_section(hosts)
        else:
            _render_warnings(snap.get("alerts") or [], hosts)

    _live()


def _cluster_ribbon(snap: Dict[str, Any], view: Dict[str, Any]) -> None:
    st.markdown(f'<div class="slds-page-title">{slds.esc(PAGE_LABEL)}</div>', unsafe_allow_html=True)
    if not snap:
        return
    hosts = snap.get("hosts") or {}
    global_status = snap.get("GLOBAL_OVERALL_STATUS") or view.get("status") or "UNKNOWN"
    items: List[Tuple[str, str]] = [
        ("Last synced", slds.esc(fmt_ts_local(snap.get("collected_at")))),
        ("Состояние кластера", _global_badge(global_status)),
        ("Связь S13 и S7", slds.esc(snap.get("s13_to_s7_connectivity") or "—")),
        ("Свежесть снимка", slds.esc(_snapshot_note(view))),
    ]
    for hid in (HOST_S13, HOST_S7):
        host = hosts.get(hid) or {}
        status = host.get("overall_status") or ("OK" if host.get("reachable") else "UNKNOWN")
        items.append((_TITLE_OF_HOST[hid], slds.status_badge(status)))
    cells = "".join(
        f'<div class="slds-ribbon__item"><span class="slds-label">{slds.esc(label)}</span>'
        f'<span class="slds-ribbon__val">{value}</span></div>'
        for label, value in items
    )
    st.markdown(f'<div class="slds-ribbon">{cells}</div>', unsafe_allow_html=True)


def _global_badge(status: Optional[str]) -> str:
    level = (status or "UNKNOWN").upper()
    if level == "OK":
        return slds.badge("Healthy", "ok")
    if level == "CRITICAL":
        return slds.badge("Critical", "crit")
    if level in ("WARNING", "STALE", "UNREACHABLE"):
        return slds.badge("Degraded Performance", "warn")
    return slds.badge(level, "neutral")


def _snapshot_note(view: Dict[str, Any]) -> str:
    status = (view.get("status") or "").upper()
    text = {"CURRENT": "актуален", "STALE": "устарел", "COLLECTOR_DOWN": "коллектор недоступен"}.get(status, view.get("status") or "—")
    age = view.get("snapshot_age_sec")
    return f"{text} · {fmt_age(age)} назад" if age is not None else text


def _render_overview(hosts: Dict[str, Any], snap: Dict[str, Any]) -> None:
    host_filter = st.radio(
        "Хост",
        ["Все", "Server 13", "Server 7"],
        horizontal=True,
        key="shm_overview_host",
        label_visibility="collapsed",
    )
    kpi_ribbon(hosts, snap)
    left, right = st.columns([7, 3], gap="medium")
    with left:
        if host_filter in ("Все", "Server 13"):
            _host_overview_card(hosts.get(HOST_S13) or {}, "SERVER 13", "CRM / AI / Документы")
        if host_filter in ("Все", "Server 7"):
            _host_overview_card(hosts.get(HOST_S7) or {}, "SERVER 7", "Источник / История / Коллекторы")
        if host_filter != "Server 7":
            render_processes_table(hosts.get(HOST_S13) or {}, "SERVER 13")
        else:
            st.caption("Процессы снимаются с S13 — выберите «Все» или «Server 13».")
    with right:
        render_consolidated_alerts(snap.get("alerts") or [], hosts)
        _render_health_services(hosts)


def _render_load_section(host: Dict[str, Any], history: List[Dict[str, Any]], host_id: str) -> None:
    """Графики истории нагрузки выбранного хоста (area, Y >= 0, общая ось X)."""
    if host:
        _host_overview_card(host, _TITLE_OF_HOST.get(host_id, host_id), host.get("role") or "Нагрузка")
    render_history_charts(history, host_id=host_id)


def _render_warnings(alerts: List[Dict[str, Any]], hosts: Dict[str, Any]) -> None:
    """Консолидированные инциденты: один блок на устройство вместо дублей алертов."""
    left, right = st.columns([7, 3], gap="medium")
    with left:
        render_consolidated_alerts(alerts, hosts)
    with right:
        _render_health_services(hosts)


def _host_overview_card(host: Dict[str, Any], title: str, role: str) -> None:
    if not host:
        st.markdown(slds.card(title, '<div class="slds-empty">Нет данных хоста в снимке.</div>'), unsafe_allow_html=True)
        return
    status = host.get("overall_status") or host.get("connectivity") or "UNKNOWN"
    cpu = host.get("cpu") or {}
    mem = host.get("memory") or {}
    temps = host.get("temperatures") or {}
    filesystems = {f.get("mount"): f for f in (host.get("filesystems") or [])}
    root = filesystems.get("/") or {}
    cpu_pct = cpu.get("usage_pct")
    temp = temps.get("display_cpu_temp_c")
    if temp is None:
        temp = cpu.get("temp_c")
    meters = [
        slds.meter("CPU", fmt_pct(cpu_pct), cpu_pct, sub=fmt_load(cpu)),
        slds.meter("RAM", fmt_pct(mem.get("ram_used_pct")), mem.get("ram_used_pct"), sub=f"доступно {fmt_bytes(mem.get('ram_available_b'))}"),
        slds.meter("Диск системы /", fmt_pct(root.get("used_pct")), root.get("used_pct"), sub=f"свободно {fmt_bytes(root.get('free_b'))}"),
        slds.meter("Температура CPU", fmt_temp(temp), None, tone="neutral", sub="датчик хоста"),
    ]
    note = ""
    if title == "SERVER 7" and not host.get("reachable"):
        note = "Мониторинг S7 · НЕТ СВЯЗИ"
    elif title == "SERVER 7" and host.get("connectivity") == "collector_failed":
        note = "Мониторинг S7 · данные устарели / ошибка коллектора"
    legacy = legacy_device(host)
    if legacy:
        note = f"{note} · " if note else ""
        note += f"{legacy} — legacy / не используется (UNUSED LEGACY NTFS), приоритет понижен, non-blocking"
    footer = f"Обновление: {fmt_ts_local(host.get('collected_at'))} · uptime {fmt_uptime(host.get('boot_time'))}"
    body = f'<div class="slds-meters">{"".join(meters)}</div><div class="slds-badges">{"".join(_host_service_badges(host, title))}</div>'
    st.markdown(
        slds.card(title, body, role=f"{role}{' · ' + note if note else ''}", badges=slds.status_badge(status), footer=footer),
        unsafe_allow_html=True,
    )


def _host_service_badges(host: Dict[str, Any], title: str) -> List[str]:
    badges: List[str] = []
    postgres = host.get("postgres") or {}
    badges.append(slds.badge_pair("PostgreSQL", status_ru(postgres.get("ui_status")), slds.status_tone(postgres.get("ui_status"))))
    if title.endswith("13"):
        gpu = host.get("gpu") or {}
        util = gpu.get("gpu_util_percent")
        gpu_idle = not util
        badges.append(slds.badge_pair("GPU", "Idle 0%" if gpu_idle else fmt_pct(util), "ok" if gpu_idle else slds.bar_tone(util)))
        ollama = host.get("ollama") or {}
        mode = (ollama.get("OLLAMA_EXECUTION_MODE") or "UNKNOWN").upper()
        badges.append(slds.badge_pair("Ollama", "Idle" if mode == "IDLE" else mode, "ok" if mode == "IDLE" else "info"))
        disk_line, disk_status = disk_summary_ru(host)
        badges.append(slds.badge_pair("Диски", disk_line, slds.status_tone(disk_status)))
    else:
        ok, total, failing = collectors_stats(host)
        badges.append(slds.badge_pair("Коллекторы", f"{ok} / {total}", "ok" if total and ok == total else "warn"))
        age = (host.get("source_freshness") or {}).get("SOURCE_AGE_SEC")
        fresh_tone = "ok" if age is not None and age < 900 else "warn"
        badges.append(slds.badge_pair("Источник", f"{fmt_age(age)} назад" if age is not None else "—", fresh_tone))
        if failing:
            badges.append(slds.badge_pair("Сбой", collector_name(failing[0]), "warn"))
    return badges


def _service_note(service: Dict[str, Any]) -> str:
    if service.get("ui_status") == "PAUSED":
        return "Остановлено по текущему плану"
    if service.get("active") == "inactive":
        return "Idle / Timer Healthy"
    return service.get("message") or (service.get("active") or "")


def _render_health_services(hosts: Dict[str, Any]) -> None:
    s13 = hosts.get(HOST_S13) or {}
    s7 = hosts.get(HOST_S7) or {}
    by_unit = {s.get("unit"): s for s in (s13.get("services") or [])}
    rows = []
    for unit in _HEALTH_SERVICE_UNITS:
        service = by_unit.get(unit)
        if not service:
            continue
        ui = service.get("ui_status")
        rows.append(slds.service_row(SERVICE_LABELS_RU.get(unit, unit), status_ru(ui), slds.status_tone(ui), _service_note(service)))
    body = "".join(rows) or '<div class="slds-empty">Нет данных служб в снимке.</div>'
    st.markdown(slds.card("Службы контроля (S13)", body), unsafe_allow_html=True)

    ok, total, _ = collectors_stats(s7)
    collector_rows = []
    for collector in s7.get("source_collectors") or []:
        ui = collector.get("ui_status")
        tone = slds.status_tone(ui)
        note = collector.get("active") or ""
        if tone != "ok":
            note = f"не активен ({collector.get('active') or 'unknown'})"
        collector_rows.append(slds.service_row(collector_name(collector), status_ru(ui), tone, note))
    cbody = "".join(collector_rows) or '<div class="slds-empty">Нет данных коллекторов.</div>'
    badge = slds.status_badge("OK" if total and ok == total else "WARNING", f"{ok} / {total}")
    st.markdown(slds.card("Коллекторы (S7)", cbody, badges=badge), unsafe_allow_html=True)


def _render_host_detail(host: Dict[str, Any], title: str, history: List[Dict[str, Any]], host_id: Optional[str] = None) -> None:
    if not host:
        st.warning("Нет данных хоста")
        return
    _host_overview_card(host, title, host.get("role") or title)
    if title.endswith("7"):
        _source_freshness_card(host, host.get("connectivity") or "reachable")
        render_collectors_table(host)

    st.markdown(section_title("Состояние дисков"), unsafe_allow_html=True)
    rows = []
    for fs in host.get("filesystems") or []:
        mount = fs.get("mount")
        label = "Система /" if mount == "/" else ("Документы /data" if mount == "/data" else mount)
        rows.append(
            {
                "Том": label,
                "Устройство": fs.get("device"),
                "Занято": fmt_pct(fs.get("used_pct")),
                "Свободно": fmt_bytes(fs.get("free_b")),
                "Inodes": fmt_pct(fs.get("inodes_used_pct")),
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)

    render_disk_table(host)
    render_services_table(host)
    render_history_charts(history, host_id=host_id)

    with st.expander("Техническая информация", expanded=False):
        st.write(f"Host id: `{host.get('host_id')}` · connectivity: `{host.get('connectivity')}`")
        st.write(f"Kernel: `{(host.get('host') or {}).get('kernel') or host.get('kernel') or '—'}`")
        st.json(
            {
                "capabilities": host.get("capabilities"),
                "temperatures": host.get("temperatures"),
                "S7_SENSORS_AVAILABLE": host.get("S7_SENSORS_AVAILABLE"),
                "S7_THERMAL_SYSFS_AVAILABLE": host.get("S7_THERMAL_SYSFS_AVAILABLE"),
                "collection_errors": host.get("collection_errors"),
                "collected_at_iso": host.get("collected_at"),
                "source_freshness": host.get("source_freshness"),
            }
        )


def _source_freshness_card(s7: Dict[str, Any], connectivity: Optional[str]) -> None:
    freshness = s7.get("source_freshness") or {}
    journals = freshness.get("journals") or freshness.get("JOURNAL") or {}
    forward = journals.get("forward") or freshness.get("FORWARD_JOURNAL") or freshness.get("forward_journal") or "—"
    backward = journals.get("backward") or freshness.get("BACKWARD_JOURNAL") or freshness.get("backward_journal") or "—"
    daily = freshness.get("DAILY_MIGRATION") or freshness.get("daily_migration") or "—"
    monitoring = freshness.get("MONITORING") or freshness.get("monitoring") or "—"
    age = freshness.get("SOURCE_AGE_SEC")
    ok, total, failing = collectors_stats(s7)
    postgres = s7.get("postgres") or {}
    items = [
        ("Последнее обновление", f"{fmt_age(age)} назад", fmt_ts_local(freshness.get("LATEST_SOURCE_UPDATE"))),
        ("Collectors", f"{ok} / {total}", ", ".join(collector_name(c) for c in failing) or "все активны"),
        ("PostgreSQL", status_ru(postgres.get("ui_status")), ""),
        ("Связь S13 и S7", connectivity or "—", ""),
        ("Journal forward / backward", f"{forward} / {backward}", ""),
        ("Daily / Monitoring", f"{daily} / {monitoring}", ""),
    ]
    body = "".join(
        f'<div class="slds-svc"><span><span class="slds-svc__name">{slds.esc(label)}</span>'
        f'<div class="slds-svc__note">{slds.esc(sub)}</div></span>'
        f'<span class="slds-svc__name">{slds.esc(value)}</span></div>'
        for label, value, sub in items
    )
    st.markdown(slds.card("Источник данных (S7)", body), unsafe_allow_html=True)
