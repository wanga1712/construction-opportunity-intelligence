"""Streamlit: Состояние серверов — multi-host UX (snapshot-only)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

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
    history_series,
    status_dot,
    status_ru,
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

_CARD_CSS = """
<style>
[data-testid="stSidebarNav"] {display:none !important;}
.shm-top {display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:.6rem;padding:.55rem .8rem;
  border-radius:10px;background:rgba(120,120,120,.08);font-size:.92rem;}
.shm-top b{margin-right:.25rem}
.shm-card{border:1px solid rgba(120,120,120,.25);border-radius:14px;padding:1rem 1.1rem;
  background:rgba(255,255,255,.55);margin-bottom:.75rem}
.shm-card h3{margin:0 0 .15rem 0;font-size:1.15rem}
.shm-role{opacity:.7;font-size:.85rem;margin-bottom:.6rem}
.shm-kpis{display:grid;grid-template-columns:1fr 1fr;gap:.55rem .8rem;margin-top:.4rem}
.shm-kpi{padding:.45rem .55rem;border-radius:10px;background:rgba(120,120,120,.07)}
.shm-kpi .lbl{font-size:.75rem;opacity:.7}
.shm-kpi .val{font-size:1.15rem;font-weight:650;line-height:1.2}
.shm-kpi .sub{font-size:.78rem;opacity:.75}
.shm-warn{border-left:4px solid #d4a017;padding:.7rem .9rem;margin:.5rem 0;
  border-radius:8px;background:rgba(212,160,23,.08)}
.shm-ok{border-left:4px solid #2e7d32}
.shm-crit{border-left:4px solid #c62828;background:rgba(198,40,40,.06)}
.shm-gray{opacity:.75}
</style>
"""


def render_system_health_page(_service=None) -> None:
    st.markdown(_CARD_CSS, unsafe_allow_html=True)
    st.title(f"🖥️ {PAGE_LABEL}")

    @st.fragment(run_every=timedelta(seconds=UI_REFRESH_SEC))
    def _live() -> None:
        section = st.radio(
            "Раздел",
            _SECTIONS,
            horizontal=True,
            key="sys_health_view",
            label_visibility="collapsed",
        )
        need_hist = section in ("SERVER 13", "SERVER 7", "Нагрузка")
        host_key = None
        if section == "SERVER 13":
            host_key = HOST_S13
        elif section == "SERVER 7":
            host_key = HOST_S7
        elif section == "Нагрузка":
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

        view = load_dashboard(
            include_history=need_hist,
            history_host=host_key,
            history_hours=hours,
        )
        assert view.get("hardware_probes") == 0
        assert view.get("s7_ssh_calls") == 0
        if section == "ОБЗОР":
            assert view.get("history_loaded") is False

        snap = view.get("snapshot") or {}
        if not view.get("ready"):
            st.warning(view.get("message") or "Collector down")
            return

        _top_bar(snap, view)
        hosts = snap.get("hosts") or {}
        history = view.get("history") or []

        # selected section → build selected detail only
        if section == "ОБЗОР":
            _render_overview(hosts, snap)
        elif section == "SERVER 13":
            _render_host_detail(hosts.get(HOST_S13) or {}, "SERVER 13", history)
        elif section == "SERVER 7":
            _render_host_detail(hosts.get(HOST_S7) or {}, "SERVER 7", history)
        elif section == "Диски":
            _render_disks_section(hosts)
        elif section == "Нагрузка":
            _render_load_section(hosts.get(host_key or HOST_S13) or {}, history)
        elif section == "Сервисы":
            _render_services_section(hosts)
        elif section == "Сеть":
            _render_network_section(hosts)
        elif section == "Процессы":
            _render_processes_section(hosts)
        else:
            _render_warnings(snap.get("alerts") or [], hosts)

    _live()


def _top_bar(snap: Dict[str, Any], view: Dict[str, Any]) -> None:
    g = snap.get("GLOBAL_OVERALL_STATUS") or view.get("status") or "UNKNOWN"
    conn = snap.get("s13_to_s7_connectivity") or "—"
    hosts = snap.get("hosts") or {}
    s13 = hosts.get(HOST_S13) or {}
    s7 = hosts.get(HOST_S7) or {}
    s7_dot = "🟢" if s7.get("reachable") else status_dot(s7.get("overall_status"))
    s7_txt = "доступен" if s7.get("reachable") else status_ru(s7.get("overall_status"))
    st.markdown(
        f"""
<div class="shm-top">
  <div><b>GLOBAL</b> {status_dot(g)} {status_ru(g)}</div>
  <div><b>S13 ↔ S7</b> {conn}</div>
  <div><b>Обновление</b> {fmt_ts_local(snap.get('collected_at'))}</div>
  <div><b>S13</b> {status_dot(s13.get('overall_status'))} {status_ru(s13.get('overall_status'))}</div>
  <div><b>S7</b> {s7_dot} {s7_txt}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _sync_service(host: Dict[str, Any]) -> Dict[str, Any]:
    for s in host.get("services") or []:
        unit = s.get("unit") or ""
        if "procurement-sync" in unit or unit.endswith("crm-procurement-sync.service"):
            return s
    return {}


def _render_overview(hosts: Dict[str, Any], snap: Dict[str, Any]) -> None:
    s13 = hosts.get(HOST_S13) or {}
    s7 = hosts.get(HOST_S7) or {}
    c1, c2 = st.columns(2)
    with c1:
        _host_overview_card(s13, "SERVER 13", "CRM / AI / Documents")
    with c2:
        _host_overview_card(s7, "SERVER 7", "Source / History / Collectors")
        _source_freshness_card(s7, snap.get("s13_to_s7_connectivity"))

    alerts = [a for a in (snap.get("alerts") or []) if a.get("level") in ("WARNING", "CRITICAL")]
    st.markdown("#### Активные предупреждения")
    if not alerts:
        st.success("Активных предупреждений нет")
    else:
        for a in alerts[:8]:
            _alert_card(a, hosts)

    # Golden V3 canary — marked as stale/unavailable in V4
    st.markdown("**Golden V3 canary:** `stale/unavailable`")


def _host_overview_card(host: Dict[str, Any], title: str, role: str) -> None:
    st_ = host.get("overall_status") or host.get("connectivity") or "UNKNOWN"
    if title == "SERVER 7":
        if host.get("reachable") is True:
            if host.get("connectivity") == "collector_failed":
                status_header = "🟢 доступен"
                monitor_status_html = "<div class='shm-role' style='color:#e65c00; font-weight:bold'>Мониторинг S7 · данные устарели / ошибка коллектора</div>"
            else:
                status_header = f"{status_dot(st_)} {status_ru(st_)}"
                monitor_status_html = ""
        else:
            status_header = f"{status_dot(st_)} {status_ru(st_)}"
            monitor_status_html = "<div class='shm-role' style='color:#cc0000; font-weight:bold'>Мониторинг S7 · НЕТ СВЯЗИ</div>"
    else:
        status_header = f"{status_dot(st_)} {status_ru(st_)}"
        monitor_status_html = ""
    cpu = host.get("cpu") or {}
    mem = host.get("memory") or {}
    temps = host.get("temperatures") or {}
    fs = {f.get("mount"): f for f in (host.get("filesystems") or [])}
    root = fs.get("/") or {}
    data = fs.get("/data") or {}
    disk_line, disk_st = disk_summary_ru(host)

    cpu_pct = cpu.get("usage_pct")
    cpu_txt = "—" if cpu_pct is None and cpu.get("usage_pct_status") == "NOT_AVAILABLE" else fmt_pct(cpu_pct)
    temp_disp = temps.get("display_cpu_temp_c")
    if temp_disp is None:
        temp_disp = cpu.get("temp_c")
    temp_st = temps.get("display_cpu_temp_status") or ("UNKNOWN" if temp_disp is None else "OK")

    pg = host.get("postgres") or {}
    crm = host.get("crm_streamlit") or {}
    collectors = host.get("source_collectors") or []
    coll_ok = sum(1 for c in collectors if c.get("ui_status") == "OK")
    sync = _sync_service(host)
    disk_temps = temps.get("disk_temperatures") or []

    if title.endswith("13"):
        gpu = host.get("gpu") or {}
        ollama = host.get("ollama") or {}
        gpu_model = gpu.get("gpu_model") or "—"
        gpu_util = gpu.get("gpu_util_percent")
        vram_u = gpu.get("gpu_vram_used_mb")
        vram_t = gpu.get("gpu_vram_total_mb")
        vram_pct = gpu.get("gpu_vram_percent")
        gpu_temp = gpu.get("gpu_temp_c")
        exec_mode = ollama.get("OLLAMA_EXECUTION_MODE") or "UNKNOWN"
        active_model = ollama.get("OLLAMA_ACTIVE_MODEL") or "—"
        power = gpu.get("gpu_power_w")
        power_lim = gpu.get("gpu_power_limit_w")
        power_txt = (
            f"{power:.0f}/{power_lim:.0f} W"
            if power is not None and power_lim is not None
            else ("—" if power is None else f"{power:.0f} W")
        )
        vram_txt = (
            f"{vram_u:.0f}/{vram_t:.0f} MB"
            if vram_u is not None and vram_t is not None
            else "—"
        )
        disk_temp_sub = " · ".join(
            f"{(d.get('device') or '').replace('/dev/', '')} {fmt_temp(d.get('temp_c'))}"
            for d in disk_temps[:3]
        ) or "—"
        services_html = (
            f"<div class='shm-kpi'><div class='lbl'>GPU</div>"
            f"<div class='val'>{fmt_pct(gpu_util)}</div>"
            f"<div class='sub'>{gpu_model}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>VRAM</div>"
            f"<div class='val'>{fmt_pct(vram_pct)}</div>"
            f"<div class='sub'>{vram_txt}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Температура GPU</div>"
            f"<div class='val'>{fmt_temp(gpu_temp)}</div>"
            f"<div class='sub'>power {power_txt}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Ollama model</div>"
            f"<div class='val' style='font-size:.95rem'>{active_model}</div>"
            f"<div class='sub'>исполнение: {exec_mode}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Система /</div>"
            f"<div class='val'>{fmt_pct(root.get('used_pct'))}</div>"
            f"<div class='sub'>свободно {fmt_bytes(root.get('free_b'))}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Документы /data</div>"
            f"<div class='val'>{fmt_pct(data.get('used_pct'))}</div>"
            f"<div class='sub'>свободно {fmt_bytes(data.get('free_b'))}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Состояние дисков</div>"
            f"<div class='val'>{status_dot(disk_st)} {disk_line}</div>"
            f"<div class='sub'>{disk_temp_sub}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>PostgreSQL</div>"
            f"<div class='val'>{status_dot(pg.get('ui_status'))} {status_ru(pg.get('ui_status'))}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>CRM Streamlit</div>"
            f"<div class='val'>{status_dot(crm.get('ui_status'))} {status_ru(crm.get('ui_status'))}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Синхронизация</div>"
            f"<div class='val'>{status_dot(sync.get('ui_status'))} {status_ru(sync.get('ui_status'))}</div>"
            f"<div class='sub'>{sync.get('health_model') or '—'} · {sync.get('result') or '—'}</div></div>"
        )
    else:
        phys = host.get("physical_disks_discovered")
        smart_n = host.get("smart_accessible_devices")
        smart_txt = "недоступен" if smart_n == 0 else str(smart_n)
        services_html = (
            f"<div class='shm-kpi'><div class='lbl'>Swap</div>"
            f"<div class='val'>{fmt_pct(mem.get('swap_used_pct'))}</div>"
            f"<div class='sub'>занято {fmt_bytes(mem.get('swap_used_b'))}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Система /</div>"
            f"<div class='val'>{fmt_pct(root.get('used_pct'))}</div>"
            f"<div class='sub'>свободно {fmt_bytes(root.get('free_b'))}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Диски</div>"
            f"<div class='val'>физ. {phys if phys is not None else '—'}</div>"
            f"<div class='sub'>SMART: {smart_txt} · темп. дисков: —</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>PostgreSQL</div>"
            f"<div class='val'>{status_dot(pg.get('ui_status'))} {status_ru(pg.get('ui_status'))}</div>"
            f"<div class='sub'>{pg.get('reachable') if pg.get('reachable') is not None else ''}</div></div>"
            f"<div class='shm-kpi'><div class='lbl'>Collectors</div>"
            f"<div class='val'>{coll_ok}/{len(collectors)} "
            f"{status_dot('OK' if coll_ok == len(collectors) and collectors else 'WARNING')}</div></div>"
        )

    st.markdown(
        f"""
<div class="shm-card">
  <h3>{title} &nbsp; {status_header}</h3>
  <div class="shm-role">{role}</div>
  {monitor_status_html}
  <div class="shm-kpis">
    <div class="shm-kpi"><div class="lbl">CPU</div><div class="val">{cpu_txt}</div>
      <div class="sub">{fmt_load(cpu)}</div></div>
    <div class="shm-kpi"><div class="lbl">Температура CPU</div><div class="val">{fmt_temp(temp_disp)}</div>
      <div class="sub">{status_dot(temp_st)} {status_ru(temp_st)}</div></div>
    <div class="shm-kpi"><div class="lbl">RAM</div><div class="val">{fmt_pct(mem.get('ram_used_pct'))}</div>
      <div class="sub">Доступно {fmt_bytes(mem.get('ram_available_b'))}</div></div>
    {services_html}
  </div>
  <div class="shm-role" style="margin-top:.7rem">Обновление: {fmt_ts_local(host.get('collected_at'))} · uptime {fmt_uptime(host.get('boot_time'))}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def _source_freshness_card(s7: Dict[str, Any], connectivity: Optional[str]) -> None:
    fr = s7.get("source_freshness") or {}
    cols = s7.get("source_collectors") or []
    ok = sum(1 for c in cols if c.get("ui_status") == "OK")
    pg = s7.get("postgres") or {}
    age = fr.get("SOURCE_AGE_SEC")
    journals = fr.get("journals") or fr.get("JOURNAL") or {}
    fwd = journals.get("forward") or fr.get("FORWARD_JOURNAL") or fr.get("forward_journal") or "—"
    bwd = journals.get("backward") or fr.get("BACKWARD_JOURNAL") or fr.get("backward_journal") or "—"
    daily = fr.get("DAILY_MIGRATION") or fr.get("daily_migration") or "—"
    mon = fr.get("MONITORING") or fr.get("monitoring") or "—"
    st.markdown(
        f"""
<div class="shm-card" style="margin-top:.8rem">
  <h3>Источник данных (S7)</h3>
  <div class="shm-kpis">
    <div class="shm-kpi"><div class="lbl">Последнее обновление</div>
      <div class="val">{fmt_age(age)} назад</div>
      <div class="sub">{fmt_ts_local(fr.get('LATEST_SOURCE_UPDATE'))}</div></div>
    <div class="shm-kpi"><div class="lbl">Collectors</div>
      <div class="val">{ok}/{len(cols)} {status_dot('OK' if ok == len(cols) and cols else 'WARNING')}</div></div>
    <div class="shm-kpi"><div class="lbl">PostgreSQL</div>
      <div class="val">{status_dot(pg.get('ui_status'))} {status_ru(pg.get('ui_status'))}</div></div>
    <div class="shm-kpi"><div class="lbl">Связь S13 ↔ S7</div>
      <div class="val">{connectivity or '—'}</div></div>
    <div class="shm-kpi"><div class="lbl">Journal forward / backward</div>
      <div class="val" style="font-size:.95rem">{fwd} / {bwd}</div></div>
    <div class="shm-kpi"><div class="lbl">Daily / Monitoring</div>
      <div class="val" style="font-size:.95rem">{daily} / {mon}</div></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_host_detail(host: Dict[str, Any], title: str, history: List[Dict[str, Any]]) -> None:
    if not host:
        st.warning("Нет данных хоста")
        return
    _host_overview_card(host, title, host.get("role") or title)
    if title.endswith("7"):
        _source_freshness_card(host, host.get("connectivity") or "reachable")
        _render_collectors_table(host)

    st.markdown("#### Хранилище")
    rows = []
    for f in host.get("filesystems") or []:
        label = (
            "Система /"
            if f.get("mount") == "/"
            else ("Документы /data" if f.get("mount") == "/data" else f.get("mount"))
        )
        rows.append(
            {
                "Том": label,
                "Устройство": f.get("device"),
                "Занято": fmt_pct(f.get("used_pct")),
                "Свободно": fmt_bytes(f.get("free_b")),
                "Inodes": fmt_pct(f.get("inodes_used_pct")),
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)

    _render_disk_table(host)
    _render_services_table(host)
    _render_history_charts(history)

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


def _render_disk_table(host: Dict[str, Any]) -> None:
    st.markdown("#### Диски")
    physical = int(host.get("physical_disks_discovered") or len(host.get("block_devices") or []))
    smart_n = host.get("smart_accessible_devices")
    if smart_n is None:
        smart_n = sum(1 for d in (host.get("disk_health") or []) if d.get("available"))
    st.caption(f"Физических дисков: **{physical}** · SMART доступен: **{smart_n}**")
    if physical > 0 and int(smart_n) == 0:
        st.info("SMART дисков: недоступен. Это не значит, что дисков 0. Температура дисков: —")

    sdb_role = host.get("sdb_role") or {}
    disk_rows = []
    for d in host.get("disk_health") or []:
        role = "—"
        badge = ""
        if d.get("device") == "/dev/sdb" and sdb_role:
            role = "Legacy / не используется"
            badge = "LEGACY"
        wear = d.get("wear") or {}
        wear_txt = "—"
        if d.get("percentage_used") is not None:
            wear_txt = f"{d.get('percentage_used')}%"
        elif wear.get("percent_used_estimate") is not None:
            wear_txt = f"{wear.get('percent_used_estimate')}%"
        temp = d.get("temperature_c")
        disk_rows.append(
            {
                "Диск": d.get("device"),
                "Модель": d.get("model"),
                "Роль": role,
                "Темп.": "—" if temp is None else f"{temp}°C",
                "SMART": d.get("overall") or "—",
                "Износ": wear_txt,
                "Realloc": d.get("reallocated_sectors"),
                "Pending": d.get("pending_sectors"),
                "STATUS": d.get("status"),
                "Метка": badge,
            }
        )
    if not disk_rows and host.get("block_devices"):
        for b in host.get("block_devices") or []:
            disk_rows.append(
                {
                    "Диск": b.get("device"),
                    "Модель": b.get("model"),
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
            "**/dev/sdb** — LEGACY / НЕ ИСПОЛЬЗУЕТСЯ: не задействован CRM / PostgreSQL / document storage. "
            "SMART PASSED ≠ полностью исправен (realloc/pending)."
        )


def _render_services_table(host: Dict[str, Any]) -> None:
    st.markdown("#### Сервисы")
    svc_rows = []
    for s in host.get("services") or []:
        unit = s.get("unit") or ""
        ui = s.get("ui_status")
        note = s.get("message") or ""
        if ui == "PAUSED":
            note = "Остановлено по текущему плану"
        svc_rows.append(
            {
                "Сервис": SERVICE_LABELS_RU.get(unit, unit),
                "Unit": unit,
                "Ожидание": s.get("expectation") or s.get("health_model") or "—",
                "Факт": s.get("active"),
                "Результат": s.get("result") or "—",
                "Статус": f"{status_dot(ui)} {status_ru(ui)}",
                "Комментарий": note,
            }
        )
    if svc_rows:
        st.dataframe(svc_rows, hide_index=True, use_container_width=True)
    else:
        st.caption("Нет данных сервисов в снимке.")


def _render_collectors_table(host: Dict[str, Any]) -> None:
    st.markdown("#### Collectors (S7)")
    rows = []
    for s in host.get("source_collectors") or []:
        unit = s.get("unit") or s.get("name") or ""
        ui = s.get("ui_status")
        rows.append(
            {
                "Collector": SERVICE_LABELS_RU.get(unit, unit),
                "Unit": unit,
                "Факт": s.get("active"),
                "Результат": s.get("result") or "—",
                "Статус": f"{status_dot(ui)} {status_ru(ui)}",
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)


def _render_history_charts(history: List[Dict[str, Any]]) -> None:
    st.markdown("#### История")
    if not history:
        st.caption("Нет точек истории для выбранного периода.")
        return
    for metric, title_m in (
        ("cpu_pct", "CPU %"),
        ("ram_used_pct", "RAM %"),
        ("cpu_temp_c", "Температура CPU"),
        ("gpu_util_pct", "Загрузка GPU, %"),
        ("gpu_temp_c", "Температура GPU, °C"),
        ("gpu_vram_pct", "Использование VRAM, %"),
        ("gpu_power_w", "Потребление GPU, W"),
        ("load_1", "Load 1"),
        ("root_used_pct", "Занятость /"),
        ("data_used_pct", "Занятость /data"),
    ):
        series = history_series(history, metric)
        if series.get(metric):
            st.caption(title_m)
            st.line_chart({title_m: series[metric]})
        elif metric.startswith("gpu_"):
            st.caption(f"{title_m} — нет точек истории (ещё не накоплено)")


def _render_disks_section(hosts: Dict[str, Any]) -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("SERVER 13")
        _render_disk_table(hosts.get(HOST_S13) or {})
    with c2:
        st.subheader("SERVER 7")
        _render_disk_table(hosts.get(HOST_S7) or {})


def _render_load_section(host: Dict[str, Any], history: List[Dict[str, Any]]) -> None:
    cpu = host.get("cpu") or {}
    mem = host.get("memory") or {}
    gpu = host.get("gpu") or {}
    ollama = host.get("ollama") or {}
    st.markdown(
        f"**CPU** {fmt_pct(cpu.get('usage_pct'))} · {fmt_load(cpu)} · "
        f"**RAM** {fmt_pct(mem.get('ram_used_pct'))} · доступно {fmt_bytes(mem.get('ram_available_b'))}"
    )
    if host.get("host_id") == HOST_S13 or (host.get("role") or "").startswith("CRM"):
        st.markdown(
            f"**GPU** {fmt_pct(gpu.get('gpu_util_percent'))} · "
            f"VRAM {fmt_pct(gpu.get('gpu_vram_percent'))} · "
            f"temp {fmt_temp(gpu.get('gpu_temp_c'))} · "
            f"Ollama `{ollama.get('OLLAMA_ACTIVE_MODEL') or '—'}` · "
            f"режим {ollama.get('OLLAMA_EXECUTION_MODE') or 'UNKNOWN'}"
        )
    _render_history_charts(history)


def _render_services_section(hosts: Dict[str, Any]) -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("SERVER 13")
        _render_services_table(hosts.get(HOST_S13) or {})
    with c2:
        st.subheader("SERVER 7")
        _render_services_table(hosts.get(HOST_S7) or {})
        _render_collectors_table(hosts.get(HOST_S7) or {})


def _render_network_section(hosts: Dict[str, Any]) -> None:
    for hid, title in ((HOST_S13, "SERVER 13"), (HOST_S7, "SERVER 7")):
        host = hosts.get(hid) or {}
        net = host.get("network") or {}
        st.subheader(title)
        if not net:
            st.caption("Нет сетевых метрик в снимке.")
            continue
        st.json(net)


def _render_processes_section(hosts: Dict[str, Any]) -> None:
    for hid, title in ((HOST_S13, "SERVER 13"), (HOST_S7, "SERVER 7")):
        host = hosts.get(hid) or {}
        procs = host.get("top_processes") or []
        st.subheader(title)
        if not procs:
            st.caption("Нет списка процессов в снимке.")
            continue
        st.dataframe(procs[:15], hide_index=True, use_container_width=True)


def _alert_card(a: Dict[str, Any], hosts: Dict[str, Any]) -> None:
    level = a.get("level") or "INFO"
    cls = "shm-crit" if level == "CRITICAL" else ("shm-warn" if level == "WARNING" else "shm-ok")
    host_id = a.get("host_id") or "?"
    target = a.get("device_or_service") or ""
    msg = a.get("message") or ""
    extra = ""
    if target == "/dev/sdb":
        role = ((hosts.get(HOST_S13) or {}).get("sdb_role") or {}).get("SDB_DATA_ROLE")
        extra = f"<div class='shm-gray'>Роль: legacy / unused ({role})</div>"
        if "pending" in msg:
            msg = "Обнаружены нестабильные сектора (pending)"
        elif "reallocated" in msg:
            msg = "Есть переназначенные сектора (reallocated)"
        elif "disk health" in msg:
            msg = "Физическое состояние диска: предупреждение (SMART PASSED ≠ полностью исправен)"
    if "sustained CPU" in msg:
        msg = "Высокая загрузка CPU (≥90% sustained)"
    st.markdown(
        f"""
<div class="{cls}">
  <b>{level}</b> · SERVER {host_id.replace('S','')} · <code>{target}</code><br/>
  {msg}<br/>
  observed={a.get('observed')} · threshold={a.get('threshold')}
  {extra}
</div>
""",
        unsafe_allow_html=True,
    )


def _render_warnings(alerts: List[Dict[str, Any]], hosts: Dict[str, Any]) -> None:
    if not alerts:
        st.success("Нет активных предупреждений")
        return
    for a in alerts:
        if a.get("level") in ("WARNING", "CRITICAL"):
            _alert_card(a, hosts)
