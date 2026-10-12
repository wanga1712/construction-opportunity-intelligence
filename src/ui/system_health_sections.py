"""Detail sections and data tables for the system health page (SLDS styling)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from src.services.system_health_config import HOST_S13, HOST_S7
from src.ui import system_health_slds as slds
from src.ui.system_health_format import (
    SERVICE_LABELS_RU,
    fmt_bytes,
    fmt_pct,
    history_points,
    status_dot,
    status_ru,
)

_TITLE_OF_HOST = {HOST_S13: "SERVER 13", HOST_S7: "SERVER 7"}
_CHART_METRICS: Tuple[Tuple[str, str, Optional[float]], ...] = (
    ("cpu_pct", "CPU, %", 100.0),
    ("ram_used_pct", "RAM, %", 100.0),
    ("cpu_temp_c", "Температура CPU, °C", None),
    ("load_1", "Load 1", None),
    ("root_used_pct", "Занятость /, %", 100.0),
    ("data_used_pct", "Занятость /data, %", 100.0),
)
_GPU_CHART_METRICS: Tuple[Tuple[str, str, Optional[float]], ...] = (
    ("gpu_util_pct", "Загрузка GPU, %", 100.0),
    ("gpu_vram_pct", "VRAM, %", 100.0),
    ("gpu_temp_c", "Температура GPU, °C", None),
    ("gpu_power_w", "Потребление GPU, W", None),
)


def section_title(text: str, size: int = 16) -> str:
    return f'<div class="slds-card__title" style="font-size:{size}px;margin:2px 0 8px 0">{slds.esc(text)}</div>'


def proc_label(proc: Dict[str, Any]) -> str:
    raw = proc.get("cmdline") or proc.get("name") or "—"
    text = str(raw).strip() or "—"
    return text if len(text) <= 64 else text[:61] + "…"


def proc_status(cpu_pct: float) -> str:
    if cpu_pct >= slds.CPU_CRIT_PCT:
        return "Critical"
    if cpu_pct > slds.PROC_RED_PCT:
        return "High"
    return "Normal"


def cpu_cell_style(value: Any) -> str:
    try:
        hot = float(value) > slds.PROC_RED_PCT
    except (TypeError, ValueError):
        return ""
    return f"color:{slds.CRIT_FG};font-weight:700" if hot else ""


def proc_rows(procs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for proc in procs or []:
        rows.append(
            {
                "PID": proc.get("pid"),
                "Команда": proc_label(proc),
                "CPU %": f"{float(proc.get('cpu_pct') or 0):.1f}%",
                "RAM": f"{float(proc.get('ram_mb') or 0):.1f} MB",
            }
        )
    return rows


def render_history_charts(history: List[Dict[str, Any]], host_id: Optional[str] = None) -> None:
    """CPU/RAM area charts (shared X domain, Y axis pinned to >= 0) plus the rest."""
    st.markdown(section_title("История нагрузки"), unsafe_allow_html=True)
    if not history:
        st.caption("Нет точек истории для выбранного периода.")
        return
    metrics = list(_CHART_METRICS)
    if any(str(r.get("metric") or "").startswith("gpu_") for r in history):
        metrics.extend(_GPU_CHART_METRICS)
    rendered = 0
    for metric, label, y_max in metrics:
        points = history_points(history, metric, host_id=host_id)
        if not points:
            continue
        slds.render_area_chart(points, label=label, y_max=y_max)
        rendered += 1
    if not rendered:
        st.caption("Нет точек истории для выбранного периода.")


def render_disk_table(host: Dict[str, Any]) -> None:
    st.markdown(section_title("Физические диски (SMART)", 15), unsafe_allow_html=True)
    physical = int(host.get("physical_disks_discovered") or len(host.get("block_devices") or []))
    smart_n = host.get("smart_accessible_devices")
    if smart_n is None:
        smart_n = sum(1 for d in (host.get("disk_health") or []) if d.get("available"))
    st.caption(f"Физических дисков: **{physical}** · SMART доступен: **{smart_n}**")
    if physical > 0 and int(smart_n) == 0:
        st.info("SMART дисков: недоступен. Это не значит, что дисков 0.")

    sdb_role = host.get("sdb_role") or {}
    disk_rows: List[Dict[str, Any]] = []
    for disk in host.get("disk_health") or []:
        role = "—"
        mark = ""
        if disk.get("device") == "/dev/sdb" and sdb_role:
            role = "Legacy / не используется"
            mark = "UNUSED LEGACY NTFS"
        wear = disk.get("wear") or {}
        wear_txt = "—"
        if disk.get("percentage_used") is not None:
            wear_txt = f"{disk.get('percentage_used')}%"
        elif wear.get("percent_used_estimate") is not None:
            wear_txt = f"{wear.get('percent_used_estimate')}%"
        temp = disk.get("temperature_c")
        disk_rows.append(
            {
                "Диск": disk.get("device"),
                "Модель": disk.get("model"),
                "Роль": role,
                "Темп.": "—" if temp is None else f"{temp}°C",
                "SMART": disk.get("overall") or "—",
                "Износ": wear_txt,
                "Realloc": disk.get("reallocated_sectors"),
                "Pending": disk.get("pending_sectors"),
                "STATUS": disk.get("status"),
                "Метка": mark,
            }
        )
    if not disk_rows and host.get("block_devices"):
        for block in host.get("block_devices") or []:
            disk_rows.append(
                {
                    "Диск": block.get("device"),
                    "Модель": block.get("model"),
                    "Роль": "—",
                    "Темп.": "—",
                    "SMART": "недоступен",
                    "Износ": "—",
                    "Realloc": "—",
                    "Pending": "—",
                    "STATUS": "UNKNOWN",
                    "Метка": "",
                }
            )
    if disk_rows:
        st.dataframe(disk_rows, hide_index=True, use_container_width=True)
    if sdb_role.get("IS_SDB_CURRENTLY_UNUSED"):
        st.caption(
            "**/dev/sdb** — UNUSED LEGACY NTFS: не задействован CRM / PostgreSQL / document storage. "
            "SMART PASSED не равен полностью исправен (realloc/pending), приоритет понижен."
        )


def render_services_table(host: Dict[str, Any]) -> None:
    st.markdown(section_title("Сервисы", 15), unsafe_allow_html=True)
    service_rows = []
    for service in host.get("services") or []:
        unit = service.get("unit") or ""
        ui = service.get("ui_status")
        note = service.get("message") or ""
        if ui == "PAUSED":
            note = "Остановлено по текущему плану"
        service_rows.append(
            {
                "Сервис": SERVICE_LABELS_RU.get(unit, unit),
                "Unit": unit,
                "Ожидание": service.get("expectation") or service.get("health_model") or "—",
                "Факт": service.get("active"),
                "Результат": service.get("result") or "—",
                "Статус": f"{status_dot(ui)} {status_ru(ui)}",
                "Комментарий": note,
            }
        )
    if service_rows:
        st.dataframe(service_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("Нет данных сервисов в снимке.")


def render_collectors_table(host: Dict[str, Any]) -> None:
    st.markdown(section_title("Коллекторы источника (S7)", 15), unsafe_allow_html=True)
    rows = []
    for collector in host.get("source_collectors") or []:
        unit = collector.get("unit") or collector.get("name") or ""
        ui = collector.get("ui_status")
        rows.append(
            {
                "Collector": SERVICE_LABELS_RU.get(unit, unit),
                "Unit": unit,
                "Факт": collector.get("active"),
                "Результат": collector.get("result") or "—",
                "Статус": f"{status_dot(ui)} {status_ru(ui)}",
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)


def render_disks_section(hosts: Dict[str, Any]) -> None:
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.markdown(section_title(_TITLE_OF_HOST[HOST_S13]), unsafe_allow_html=True)
        render_disk_table(hosts.get(HOST_S13) or {})
    with c2:
        st.markdown(section_title(_TITLE_OF_HOST[HOST_S7]), unsafe_allow_html=True)
        render_disk_table(hosts.get(HOST_S7) or {})


def render_services_section(hosts: Dict[str, Any]) -> None:
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.markdown(section_title(_TITLE_OF_HOST[HOST_S13]), unsafe_allow_html=True)
        render_services_table(hosts.get(HOST_S13) or {})
    with c2:
        st.markdown(section_title(_TITLE_OF_HOST[HOST_S7]), unsafe_allow_html=True)
        render_services_table(hosts.get(HOST_S7) or {})
        render_collectors_table(hosts.get(HOST_S7) or {})


def render_network_section(hosts: Dict[str, Any]) -> None:
    for hid in (HOST_S13, HOST_S7):
        host = hosts.get(hid) or {}
        network = host.get("network") or {}
        st.markdown(section_title(_TITLE_OF_HOST[hid]), unsafe_allow_html=True)
        if not network:
            st.caption("Нет сетевых метрик в снимке.")
            continue
        st.json(network)


def render_processes_section(hosts: Dict[str, Any]) -> None:
    """Топ процессов по CPU (сортировка по CPU desc) для каждого хоста снимка."""
    for hid in (HOST_S13, HOST_S7):
        render_processes_table(hosts.get(hid) or {}, _TITLE_OF_HOST[hid])


def render_processes_table(host: Dict[str, Any], title: str) -> None:
    """Топ процессов по CPU: PID / Команда / CPU% / RAM / Статус / Действие (CPU > 80% — красным)."""
    tops = host.get("top_processes")
    if isinstance(tops, dict):
        by_cpu = tops.get("by_cpu") or []
    elif isinstance(tops, list):
        by_cpu = tops
    else:
        by_cpu = []
    st.markdown(section_title(f"Топ процессов по CPU — {title}"), unsafe_allow_html=True)
    if not by_cpu:
        st.caption("Нет списка процессов в снимке.")
        return
    rows = []
    for proc in by_cpu[:15]:
        cpu = float(proc.get("cpu_pct") or 0)
        rows.append(
            {
                "PID": proc.get("pid"),
                "Команда": proc_label(proc),
                "CPU, %": round(cpu, 1),
                "RAM, МБ": round(float(proc.get("ram_mb") or 0), 1),
                "Статус": proc_status(cpu),
                "Действие": "На разбор" if cpu >= slds.CPU_CRIT_PCT else "—",
            }
        )
    frame = pd.DataFrame(rows)
    styled = frame.style.format({"CPU, %": "{:.1f}", "RAM, МБ": "{:.1f}"}).map(cpu_cell_style, subset=["CPU, %"])
    st.dataframe(styled, hide_index=True, use_container_width=True)
    st.caption("Действия только для чтения: UI не останавливает и не перезапускает процессы (SYSTEM_HEALTH_MUTATING_ACTIONS=0).")
