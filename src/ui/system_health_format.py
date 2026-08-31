"""Human-readable formatters for system health UI (Russian primary)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

SERVICE_LABELS_RU = {
    "crm-streamlit.service": "CRM Streamlit",
    "postgresql.service": "PostgreSQL",
    "crm-system-health-collector.service": "Мониторинг серверов",
    "ollama.service": "Модель Ollama",
    "tender-docs-daemon.service": "Парсер документов V3",
    "crm-v3-learning-observer.service": "Наблюдатель обучения V3",
    "crm-v3-shadow-predictor.service": "Теневой предсказатель V3",
    "crm-v3-autonomous-worker.service": "Автономный воркер V3",
    "crm-v3-learning-dataset.timer": "Таймер сборщика датасетов V3",
    "crm-v3-learning-dataset.service": "Сборщик датасетов V3",
    "tendermonitor-eis-parser.service": "Source parser",
    "tendermonitor-eis-parser-backward.service": "Backward parser",
    "tendermonitor-daily-migration.timer": "Daily migration",
    "tendermonitor-monitoring.timer": "Monitoring",
}


def fmt_bytes(n: Optional[float]) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit, div in (("ТБ", 1e12), ("ГБ", 1e9), ("МБ", 1e6), ("КБ", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f} {unit}"
    return f"{int(n)} Б"


def fmt_pct(n: Optional[float], digits: int = 1) -> str:
    if n is None:
        return "—"
    return f"{float(n):.{digits}f}%"


def fmt_temp(n: Optional[float]) -> str:
    if n is None:
        return "Недоступно"
    return f"{float(n):.0f}°C"


def fmt_load(cpu: Dict[str, Any]) -> str:
    l1, l5, l15 = cpu.get("load_1"), cpu.get("load_5"), cpu.get("load_15")
    if l1 is None:
        return "—"
    threads = cpu.get("threads") or cpu.get("cores") or "?"
    return f"{float(l1):.2f} / {float(l5 or 0):.2f} / {float(l15 or 0):.2f} · {threads} потоков"


def fmt_ts_local(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        ts = datetime.fromisoformat(iso)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        local = ts.astimezone()
        return local.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return str(iso)[:19]


def fmt_age(sec: Optional[float]) -> str:
    if sec is None:
        return "—"
    sec = float(sec)
    if sec < 60:
        return f"{sec:.1f} сек"
    if sec < 3600:
        return f"{sec / 60:.1f} мин"
    return f"{sec / 3600:.1f} ч"


def fmt_uptime(boot_time: Optional[float]) -> str:
    if not boot_time:
        return "—"
    try:
        import time

        sec = max(0, int(time.time() - float(boot_time)))
        d, rem = divmod(sec, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        parts = []
        if d:
            parts.append(f"{d} д")
        if h or d:
            parts.append(f"{h} ч")
        parts.append(f"{m} мин")
        return " ".join(parts)
    except Exception:
        return "—"


def status_dot(status: Optional[str]) -> str:
    s = (status or "UNKNOWN").upper()
    if s in ("OK", "CURRENT", "PASSED", "ONESHOT_RUNNING", "TIMER_HEALTHY", "ONESHOT_IDLE"):
        return "🟢"
    if s in ("WARNING", "STALE", "UNREACHABLE"):
        return "🟡"
    if s in ("CRITICAL", "COLLECTOR_DOWN", "FAILED"):
        return "🔴"
    if s in ("PAUSED", "UNKNOWN", "INFO", "N/A"):
        return "⚪"
    return "⚪"


def status_ru(status: Optional[str]) -> str:
    s = (status or "UNKNOWN").upper()
    mapping = {
        "OK": "НОРМА",
        "WARNING": "ПРЕДУПРЕЖДЕНИЕ",
        "CRITICAL": "КРИТИЧНО",
        "PAUSED": "ПАУЗА",
        "UNKNOWN": "Н/Д",
        "UNREACHABLE": "НЕТ СВЯЗИ",
        "STALE": "УСТАРЕЛО",
        "CURRENT": "АКТУАЛЬНО",
        "COLLECTOR_FAILED": "ОШИБКА КОЛЛЕКТОРА",
        "DATA_UNAVAILABLE": "ДАННЫЕ НЕДОСТУПНЫ",
        "HOST_DOWN": "СЕРВЕР ВЫКЛЮЧЕН",
        "SERVICE_DOWN": "СЕРВИС ОСТАНОВЛЕН",
    }
    return mapping.get(s, s)


def disk_summary_ru(host: Dict[str, Any]) -> Tuple[str, str]:
    summary = host.get("disk_summary") or {}
    ok = int(summary.get("OK") or 0)
    warn = int(summary.get("WARNING") or 0)
    crit = int(summary.get("CRITICAL") or 0)
    physical = int(host.get("physical_disks_discovered") or 0)
    smart_n = host.get("smart_accessible_devices")
    if smart_n is None:
        smart_n = ok + warn + crit
    if physical > 0 and int(smart_n) == 0:
        return f"Физических дисков: {physical} · SMART недоступен", "UNKNOWN"
    line = f"{ok} исправны · {warn} предупр. · {crit} крит."
    status = "CRITICAL" if crit else ("WARNING" if warn else "OK")
    return line, status


def history_series(rows: List[Dict[str, Any]], metric: str) -> Dict[str, List[float]]:
    xs: List[str] = []
    ys: List[float] = []
    for r in rows:
        if r.get("metric") != metric or r.get("value") is None:
            continue
        try:
            ts = datetime.fromtimestamp(float(r["ts"]))
            xs.append(ts.strftime("%H:%M"))
            ys.append(float(r["value"]))
        except Exception:
            continue
    return {"t": xs, metric: ys}
