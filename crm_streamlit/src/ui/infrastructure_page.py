"""Infrastructure dashboard for parser/document daemons."""
from __future__ import annotations

import streamlit as st

from src.ui.processing_quality_ui import render_processing_quality_tab
from src.services.infrastructure_status import (
    acknowledge_alert,
    get_nyx_status,
    get_queue_summary,
    get_recent_queue_errors,
    get_system_alerts,
    get_worker_logs,
    get_worker_status,
)


def _status_badge(value: str | None) -> str:
    if value in ("active", "OK_no_docs"):
        return "🟢"
    if value in ("inactive", "failed", "stopped"):
        return "🔴"
    return "🟡"


def render_infrastructure_page(service) -> None:
    st.title("🖥 Инфраструктура")
    st.caption("Где что крутится: nyx хранит БД и парсер ЕИС, sergey обрабатывает документы.")

    if st.button("↻ Проверить сейчас", use_container_width=True):
        st.cache_data.clear()

    # Системные алерты (3 consecutive download errors и т.п.)
    alerts = get_system_alerts(service.tender_db)
    if alerts:
        with st.expander(f"⚠️ Системные алерты: {len(alerts)}", expanded=True):
            for alert in alerts:
                col_msg, col_btn = st.columns([5, 1])
                with col_msg:
                    ts = alert.get("created_at", "")
                    w = alert.get("worker_id", "?")
                    st.error(f"**[worker {w}]** {alert.get('message', '')}  \n_{ts}_")
                with col_btn:
                    if st.button("✓", key=f"ack_{alert.get('id')}", help="Подтвердить"):
                        acknowledge_alert(service.tender_db, alert["id"])
                        st.rerun()

    nyx = get_nyx_status()
    worker = get_worker_status()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### nyx / 10.0.0.7")
        st.caption("БД + EIS-парсер + мониторинг; document_processor здесь не запускать.")
        st.metric("EIS parser", f"{_status_badge(nyx.get('eis'))} {nyx.get('eis') or '—'}")
        st.metric("Monitoring timer", f"{_status_badge(nyx.get('monitor'))} {nyx.get('monitor') or '—'}")
        st.metric("Document daemon", f"{_status_badge(nyx.get('docs'))} {nyx.get('docs') or '—'}")
        st.caption(nyx.get("uptime") or nyx.get("raw") or nyx.get("error") or "")

    with c2:
        st.markdown("### sergey / 10.0.0.13")
        st.caption("Рабочий ПК: document_processor.daemon + локальная модель/Ollama.")
        svc_open = worker.get("service_open") or worker.get("service") or "—"
        svc_awd = worker.get("service_awarded") or "—"
        st.metric("Daemon open", f"{_status_badge(svc_open)} {svc_open}")
        st.metric("Daemon awarded", f"{_status_badge(svc_awd)} {svc_awd}")
        daemon_count = worker.get("daemon") or "—"
        st.metric("Процессов daemon", daemon_count)
        st.metric("Load", worker.get("load") or "—")
        st.caption(worker.get("mem") or "")
        st.caption(worker.get("uptime") or worker.get("error") or "")

    st.markdown("### Очередь обработки документов")
    summary = get_queue_summary(service.tender_db)
    if summary.get("ok"):
        rows = summary.get("rows") or []
        if rows:
            cols = st.columns(max(1, len(rows)))
            for col, row in zip(cols, rows):
                col.metric(str(row.get("status")), int(row.get("count") or 0))
    else:
        st.warning(summary.get("error") or "Очередь недоступна")

    tab_errors, tab_logs, tab_quality, tab_rules = st.tabs(
        ["Ошибки / no_links", "Логи sergey", "Качество обработки", "Правила"]
    )
    with tab_errors:
        rows = get_recent_queue_errors(service.tender_db, limit=50)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.success("Свежих error/no_links не найдено.")

    with tab_quality:
        render_processing_quality_tab(service.tender_db)

    with tab_logs:
        if st.button("Показать последние 80 строк", key="infra_logs"):
            logs = get_worker_logs(80)
            st.code(logs.output or logs.error or "нет вывода")
        else:
            st.info("Логи не грузятся автоматически, чтобы не тормозить страницу.")

    with tab_rules:
        st.markdown(
            """
- `nyx / 10.0.0.7`: база `tender_monitor`, EIS-парсер, мониторинг.
- `sergey / 10.0.0.13`: единственный активный document daemon.
- На `nyx` document daemon отключён и не должен запускаться.
- Новые закупки поднимаются в приоритет при старте демона и ежедневно утром.
- `no_links` после registry lookup fix можно отдельно возвращать в очередь на повтор.
            """
        )

