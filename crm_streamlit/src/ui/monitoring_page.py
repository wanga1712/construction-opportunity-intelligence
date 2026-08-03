"""Server monitoring + pipeline analytics dashboard."""
from __future__ import annotations
import subprocess
from datetime import datetime

import pandas as pd
import streamlit as st

_WORKERS = [
    ("tender-docs-daemon-open",      13, "44/223 open"),
    ("tender-docs-daemon-open-2",    15, "44/223 open"),
    ("tender-docs-daemon-open-3",    16, "44/223 open"),
    ("tender-docs-daemon-awarded",   14, "44/223 awarded"),
    ("tender-docs-daemon-awarded-2", 17, "44/223 awarded"),
]
_CPU_WARN, _CPU_CRIT = 60, 75
_GPU_WARN, _GPU_CRIT = 65, 80


def _tcolor(t, warn, crit):
    if t is None:
        return "—"
    if t >= crit:
        return f"🔴 {t}°C"
    if t >= warn:
        return f"🟡 {t}°C"
    return f"🟢 {t}°C"


@st.cache_data(ttl=55)
def _metrics(db, hours):
    rows = db.execute_query(
        "SELECT recorded_at, cpu_temp, gpu_temp, "
        "ROUND(ram_used_mb*100.0/NULLIF(ram_total_mb,0),1) AS ram_pct, "
        "load_1min, load_5min, cpu_pct "
        "FROM server_metrics WHERE server_id=13 "
        "AND recorded_at >= NOW() - INTERVAL '%s hours' ORDER BY recorded_at ASC",
        (hours,))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["recorded_at"] = pd.to_datetime(df["recorded_at"])
    df = df.set_index("recorded_at")
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@st.cache_data(ttl=30)
def _queue_summary(db):
    rows = db.execute_query(
        "SELECT status, COUNT(*) AS cnt FROM document_processing_queue GROUP BY status") or []
    return {r["status"]: int(r["cnt"]) for r in rows}


@st.cache_data(ttl=30)
def _in_progress(db):
    return db.execute_query(
        "SELECT contract_reg_number, worker_id, started_at "
        "FROM document_processing_queue WHERE status='in_progress' ORDER BY started_at") or []


@st.cache_data(ttl=30)
def _hourly_throughput(db, hours=24):
    rows = db.execute_query(
        "SELECT DATE_TRUNC('hour', completed_at) AS h, COUNT(*) AS cnt "
        "FROM document_processing_queue "
        "WHERE status='completed' AND completed_at >= NOW() - INTERVAL '%s hours' "
        "GROUP BY h ORDER BY h",
        (hours,)) or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["h"] = pd.to_datetime(df["h"])
    df["cnt"] = pd.to_numeric(df["cnt"])
    return df.set_index("h")


@st.cache_data(ttl=30)
def _avg_duration_minutes(db):
    rows = db.execute_query(
        "SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at)))/60.0 AS avg_min "
        "FROM document_processing_queue "
        "WHERE status='completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
        "AND completed_at >= NOW() - INTERVAL '6 hours'") or []
    if not rows or rows[0]["avg_min"] is None:
        return None
    return float(rows[0]["avg_min"])


@st.cache_data(ttl=30)
def _recent_errors(db):
    return db.execute_query(
        "SELECT contract_reg_number, worker_id, error_message, started_at "
        "FROM document_processing_queue "
        "WHERE error_message IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 15") or []


@st.cache_data(ttl=30)
def _completed_4h(db):
    rows = db.execute_query(
        "SELECT COUNT(*) AS cnt FROM document_processing_queue "
        "WHERE status='completed' AND completed_at >= NOW() - INTERVAL '4 hours'") or []
    return int(rows[0]["cnt"]) if rows else 0


@st.cache_data(ttl=30)
def _alerts(db):
    return db.execute_query(
        "SELECT alert_type, message, created_at FROM daemon_alerts "
        "WHERE acknowledged=FALSE ORDER BY created_at DESC LIMIT 10") or []


def _daemon_status():
    out = []
    for svc, wid, desc in _WORKERS:
        try:
            r = subprocess.run(["systemctl", "is-active", svc],
                               capture_output=True, text=True, timeout=5)
            status = r.stdout.strip() or "unknown"
        except Exception:
            status = "unreachable"
        out.append({"Сервис": svc, "worker": wid, "Источник": desc,
                    "Статус": f"{'🟢' if status == 'active' else '🔴'} {status}"})
    return out


def render_monitoring_page(service) -> None:
    st.title("📊 Мониторинг и аналитика")

    hours = st.sidebar.slider("История (часов)", 1, 48, 6)
    if st.sidebar.button("↻ Обновить", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    db = getattr(service, "tender_db", None)
    if not db:
        st.error("Нет подключения к БД")
        return

    # ── 1. Сервер ──────────────────────────────────────────────────────────
    st.subheader("🖥️ Сервер 13")
    df_m = _metrics(db, hours)
    if not df_m.empty:
        last = df_m.iloc[-1]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("CPU темп",  _tcolor(int(last.get("cpu_temp") or 0),  _CPU_WARN, _CPU_CRIT))
        c2.metric("GPU темп",  _tcolor(int(last.get("gpu_temp") or 0),  _GPU_WARN, _GPU_CRIT))
        c3.metric("RAM",       f"{last.get('ram_pct') or 0:.0f}%")
        c4.metric("Load 1m",   f"{last.get('load_1min') or 0:.2f}")
        c5.metric("CPU %",     f"{last.get('cpu_pct') or 0}%")
        st.caption(f"Обновлено: {df_m.index[-1].strftime('%H:%M:%S')}")

        col_t, col_l = st.columns(2)
        with col_t:
            st.markdown("**Температура**")
            st.line_chart(df_m[["cpu_temp", "gpu_temp"]].rename(
                columns={"cpu_temp": "CPU °C", "gpu_temp": "GPU °C"}), height=180)
        with col_l:
            st.markdown("**Нагрузка и RAM**")
            st.line_chart(df_m[["load_1min", "load_5min", "ram_pct"]].rename(
                columns={"load_1min": "Load 1m", "load_5min": "Load 5m", "ram_pct": "RAM %"}), height=180)
    else:
        st.info("Данных о метриках пока нет (скрипт пишет раз в минуту)")

    st.divider()

    # ── 2. Очередь: сводка ─────────────────────────────────────────────────
    st.subheader("📋 Очередь обработки")
    q = _queue_summary(db)
    in_prog = _in_progress(db)
    done4h  = _completed_4h(db)
    avg_min = _avg_duration_minutes(db)

    pending     = q.get("pending", 0)
    in_prog_cnt = q.get("in_progress", len(in_prog))
    completed   = q.get("completed", 0)
    no_links    = q.get("no_links", 0)
    expired     = q.get("sales_window_expired", 0)

    rate_per_min = done4h / 240 if done4h else None
    eta_str = "—"
    if rate_per_min and pending > 0:
        eta_min = pending / rate_per_min
        eta_str = f"{int(eta_min // 60)}ч {int(eta_min % 60)}мин"
    elif pending == 0:
        eta_str = "Очередь пуста"

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("⏳ Ожидает",      pending)
    m2.metric("⚙️ В работе",     in_prog_cnt)
    m3.metric("✅ Готово (4ч)",  done4h)
    m4.metric("✅ Всего",        completed)
    m5.metric("🔗 Нет ссылок",   no_links)
    m6.metric("📅 Просроченные", expired)

    fc1, fc2, fc3 = st.columns(3)
    fc1.metric("⏱️ Ср. время контракта",
               f"{avg_min:.0f} мин" if avg_min else "нет данных")
    fc2.metric("🚀 Скорость (4ч)",
               f"{done4h / 4:.1f} контр/ч" if done4h else "—")
    fc3.metric("🏁 ETA очереди", eta_str)

    if in_prog:
        st.markdown("**Сейчас обрабатываются:**")
        now = datetime.utcnow()
        rows_ip = []
        for r in in_prog:
            elapsed = "—"
            if r.get("started_at"):
                sec = int((now - r["started_at"].replace(tzinfo=None)).total_seconds())
                elapsed = f"{sec // 60}м {sec % 60}с"
            rows_ip.append({
                "Контракт": r.get("contract_reg_number", ""),
                "Worker":   r.get("worker_id", ""),
                "Время":    elapsed,
            })
        st.dataframe(pd.DataFrame(rows_ip), use_container_width=True, hide_index=True)
    else:
        st.caption("Нет задач в статусе in_progress")

    st.divider()

    # ── 3. Производительность по часам ─────────────────────────────────────
    st.subheader("📈 Производительность")
    df_h = _hourly_throughput(db, max(hours, 24))
    if not df_h.empty:
        idx = pd.date_range(df_h.index.min(), df_h.index.max(), freq="h")
        df_h = df_h.reindex(idx, fill_value=0)
        st.bar_chart(df_h["cnt"].rename("Контракты/ч"), height=220, use_container_width=True)
        total_shown = int(df_h["cnt"].sum())
        active_hours = df_h[df_h["cnt"] > 0]
        avg_active = active_hours["cnt"].mean() if not active_hours.empty else 0
        st.caption(f"За период: {total_shown} контрактов, "
                   f"средняя скорость в активные часы: {avg_active:.1f} контр/ч")
    else:
        st.info("Нет данных о завершённых задачах за выбранный период")

    st.divider()

    # ── 4. Статус демонов ──────────────────────────────────────────────────
    st.subheader("🤖 Демоны")
    st.dataframe(pd.DataFrame(_daemon_status()), use_container_width=True, hide_index=True)

    st.divider()

    # ── 5. Ошибки ──────────────────────────────────────────────────────────
    errors = _recent_errors(db)
    if errors:
        st.subheader(f"❌ Последние ошибки ({len(errors)})")
        err_df = pd.DataFrame([{
            "Контракт": e.get("contract_reg_number", ""),
            "Worker":   e.get("worker_id", ""),
            "Время":    str(e.get("started_at", "")),
            "Ошибка":   str(e.get("error_message", ""))[:120],
        } for e in errors])
        st.dataframe(err_df, use_container_width=True, hide_index=True)

    # ── 6. Системные алерты ────────────────────────────────────────────────
    alerts = _alerts(db)
    if alerts:
        st.subheader("⚠️ Алерты")
        for a in alerts:
            st.warning(f"[{a.get('alert_type')}] {a.get('message')} — {a.get('created_at')}")
