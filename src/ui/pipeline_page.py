"""«Конвейер» — наблюдаемость воркеров, intake, feeder, sync и нагрузки S13.

Read-only: показывает, как новые закупки попадают в очередь и чем занят
сервер. Тяжёлые данные не грузятся — только bounded агрегаты и journal.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

import streamlit as st

from src.services import pipeline_observability as pov
from src.ui.components.queue_first.pipeline_line import pipeline_line_text, _CSS


@st.cache_data(ttl=25, show_spinner=False)
def _status() -> Dict[str, Any]:
    return pov.load_pipeline_status(cycle_limit=8)


def render_pipeline_page(service=None) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.title("Конвейер")
    st.caption(
        "Путь закупки: S7 / tender_monitor → crm-procurement-sync → crm_procurements + "
        "scope authority → crm-v3-factual-feeder → document_processing_queue (S13_V4) → "
        "band-воркеры → evidence/medal."
    )
    c1, c2 = st.columns([3, 1])
    with c1:
        auto = st.toggle("Авто-обновление (30 с)", key="pipeline_auto")
    with c2:
        if st.button("Обновить сейчас", use_container_width=True, key="pipeline_refresh"):
            _status.clear()
            st.rerun()

    if auto:
        _live_body()
    else:
        _render_body()


@st.fragment(run_every=timedelta(seconds=30))
def _live_body() -> None:
    _render_body()


def _render_body() -> None:
    status = _status()
    data = pov.load_pipeline_line()
    st.markdown(
        f'<div class="qf-pipeline">{pipeline_line_text(data)}</div>',
        unsafe_allow_html=True,
    )

    _render_queue(status.get("queue") or {})
    _render_intake(status.get("intake") or {})
    _render_feeder(status)
    _render_sync(status)
    _render_workers(status)
    _render_host(status.get("host") or {})


def _render_queue(q: Dict[str, Any]) -> None:
    st.subheader("Очередь документов (S13_V4)")
    a, b, c, d, e, f = st.columns(6)
    a.metric("Pending", q.get("pending"))
    b.metric("Processing", q.get("processing"))
    c.metric("Completed", q.get("completed"))
    d.metric("Failed", q.get("failed"))
    e.metric("No links", q.get("no_links"))
    f.metric("Всего", q.get("total"))


def _render_intake(intake: Dict[str, Any]) -> None:
    st.subheader("Intake — новые закупки в очереди")
    last = intake.get("last_created")
    hours = intake.get("hours_since")
    n24 = intake.get("new_24h")
    if hours is None:
        st.info("Нет данных о поступлении.")
    elif float(hours) >= 6:
        st.warning(
            f"⚠ Новых закупок нет {round(float(hours))} ч. "
            f"Последняя: {last}. За 24 ч: {n24}."
        )
    else:
        st.success(f"Последняя новая закупка: {last} ({round(float(hours))} ч назад). За 24 ч: {n24}.")
    rows = intake.get("by_hour") or []
    if rows:
        st.bar_chart(
            {"Час": [r["h"] for r in rows], "Новых": [r["n"] for r in rows]},
            x="Час", y="Новых", height=220,
        )


def _render_feeder(status: Dict[str, Any]) -> None:
    st.subheader("Feeder — admit закупок в очередь")
    last = status.get("feeder") or {}
    a, b, c = st.columns(3)
    a.metric("Admitted (последний цикл)", last.get("admitted_count"))
    b.metric("Glubina очереди", last.get("queue_depth_after"))
    c.metric("Reconciled", last.get("reconciled_updated"))
    cycles = status.get("feeder_cycles") or []
    if cycles:
        st.dataframe(_table(cycles, ["at", "admitted_count", "queue_depth_after", "live_lane_depth_after", "reconciled_updated"]),
                     use_container_width=True, hide_index=True)
    else:
        st.caption("Журнал feeder недоступен (нет journalctl в этой среде).")


def _render_sync(status: Dict[str, Any]) -> None:
    st.subheader("Sync — источник S7 → CRM")
    last = status.get("sync") or {}
    a, b, c, d, e = st.columns(5)
    a.metric("44-ФЗ open", last.get("source_open_44"))
    b.metric("223-ФЗ open", last.get("source_open_223"))
    c.metric("Inserted", last.get("inserted"))
    d.metric("Updated", last.get("updated"))
    e.metric("Errors", last.get("errors"))
    if (last.get("source_open_44") == 0 and last.get("source_open_223") == 0):
        st.warning(
            "Источник не отдаёт открытых закупок (44-ФЗ 0 / 223-ФЗ 0) — "
            "именно поэтому очередь не пополняется. Проверять сторону S7/tender_monitor."
        )
    runs = status.get("sync_runs") or []
    if runs:
        st.dataframe(
            _table(runs, ["at", "source_open_44", "source_open_223", "inserted", "updated",
                          "errors", "runtime_seconds", "awarded_relevant"]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("Журнал sync недоступен (нет journalctl в этой среде).")


def _render_workers(status: Dict[str, Any]) -> None:
    st.subheader("Воркеры")
    workers = status.get("workers") or []
    if workers:
        st.dataframe(
            [
                {
                    "unit": w["unit"], "роль": w["label"], "active": w["active"],
                    "busy": "да" if w["busy"] else "нет",
                    "последний лог": w.get("last_log_at"),
                    "сообщение": (w.get("last_message") or "")[:120],
                }
                for w in workers
            ],
            use_container_width=True, hide_index=True,
        )
    st.markdown("**CRM V3 сервисы и таймеры**")
    st.dataframe(
        [{"unit": s["unit"], "роль": s["label"], "active": s["active"]}
         for s in (status.get("crm_services") or []) + (status.get("timers") or [])],
        use_container_width=True, hide_index=True,
    )


def _render_host(host: Dict[str, Any]) -> None:
    st.subheader("Нагрузка S13")
    cpu = host.get("cpu_pct")
    a, b, c, d = st.columns(4)
    a.metric("CPU", f"{round(cpu)}%" if cpu is not None else "н/д")
    b.metric("Load 1m", host.get("load_1"))
    c.metric("Ядер", host.get("core_count"))
    d.metric("Ollama CPU", f"{round(host.get('ollama_pct'))}%" if host.get("ollama_pct") is not None else "н/д")
    tops = host.get("top_cpu") or []
    if tops:
        st.markdown("**Топ по CPU**")
        st.dataframe(
            [{"pid": p.get("pid"), "процесс": p.get("name"), "CPU %": p.get("cpu_pct"),
              "RAM МБ": p.get("ram_mb")} for p in tops],
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("Процессные пробы недоступны в этой среде (не Linux).")


def _table(rows: List[Dict[str, Any]], cols: List[str]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        item = {"время": r.get("at")}
        for c in cols:
            if c == "at":
                continue
            item[c] = r.get(c)
        out.append(item)
    return out
