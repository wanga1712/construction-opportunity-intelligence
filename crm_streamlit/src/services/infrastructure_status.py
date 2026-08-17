"""Operational status helpers for TenderMonitor infrastructure."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


WORKER_HOST = os.environ.get("S13_SSH_HOST", "")
WORKER_USER = os.environ.get("S13_SSH_USER", "")
WORKER_KEY = os.environ.get("S13_SSH_IDENTITY", "")
WORKER_SERVICE_OPEN = "tender-docs-daemon-open.service"
WORKER_SERVICE_AWARDED = "tender-docs-daemon-awarded.service"
WORKER_SERVICE = WORKER_SERVICE_OPEN  # backward compat alias for logs

NYX_HOST = os.environ.get("S7_SSH_HOST", "")
NYX_USER = os.environ.get("S7_SSH_USER", "")


@dataclass
class CommandResult:
    ok: bool
    output: str
    error: str = ""


def _run(cmd: list[str], timeout: int = 15) -> CommandResult:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return CommandResult(proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip())
    except Exception as exc:
        return CommandResult(False, "", str(exc))


def ssh_worker(command: str, timeout: int = 15) -> CommandResult:
    if not WORKER_HOST or not WORKER_USER:
        return CommandResult(False, "", "S13_SSH_HOST/S13_SSH_USER missing")
    cmd = ["ssh", "-o", "ConnectTimeout=8", f"{WORKER_USER}@{WORKER_HOST}", command]
    if WORKER_KEY:
        cmd[1:1] = ["-i", WORKER_KEY]
    return _run(cmd, timeout=timeout)


def ssh_nyx(command: str, timeout: int = 15) -> CommandResult:
    if not NYX_HOST or not NYX_USER:
        return CommandResult(False, "", "S7_SSH_HOST/S7_SSH_USER missing")
    return _run([
        "ssh",
        "-o",
        "ConnectTimeout=8",
        f"{NYX_USER}@{NYX_HOST}",
        command,
    ], timeout=timeout)


def get_worker_status() -> dict:
    cmd = (
        "echo HOST=$(hostname); "
        "echo UPTIME=$(uptime -p); "
        f"echo SERVICE_OPEN=$(systemctl is-active {WORKER_SERVICE_OPEN} 2>/dev/null || true); "
        f"echo SERVICE_AWARDED=$(systemctl is-active {WORKER_SERVICE_AWARDED} 2>/dev/null || true); "
        "echo OLLAMA=$(pgrep -af 'ollama serve' | head -1 || true); "
        "echo DAEMON=$(pgrep -af 'document_processor.daemon' | wc -l || true); "
        "echo LOAD=$(cat /proc/loadavg); "
        "free -h | awk '/Mem:/ {print \"MEM=\"$3\"/\"$2\" avail=\"$7}'"
    )
    res = ssh_worker(cmd)
    return _parse_key_values(res, host=WORKER_HOST, role="document_worker")


def get_nyx_status() -> dict:
    cmd = (
        "echo HOST=$(hostname); "
        "echo UPTIME=$(uptime -p); "
        "echo EIS=$(systemctl is-active tendermonitor-eis-parser.service 2>/dev/null || true); "
        "echo MONITOR=$(systemctl is-active tendermonitor-monitoring.timer 2>/dev/null || true); "
        "echo DOCS=$(pgrep -af 'document_processor.daemon' | head -1 || echo OK_no_docs); "
        "echo LOAD=$(cat /proc/loadavg)"
    )
    res = ssh_nyx(cmd)
    return _parse_key_values(res, host=NYX_HOST, role="db_eis_parser")


def _parse_key_values(res: CommandResult, *, host: str, role: str) -> dict:
    data = {
        "host": host,
        "role": role,
        "ok": res.ok,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "error": res.error if not res.ok else "",
        "raw": res.output,
    }
    for line in (res.output or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.lower()] = value.strip()
    return data


def get_queue_summary(tender_db) -> dict:
    if not tender_db:
        return {"ok": False, "error": "Tender DB is not connected"}
    try:
        rows = tender_db.execute_query(
            """
            SELECT status, COUNT(*) AS count
            FROM document_processing_queue
            GROUP BY status
            ORDER BY status
            """
        ) or []
        return {"ok": True, "rows": rows}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_recent_queue_errors(tender_db, limit: int = 30) -> list[dict]:
    if not tender_db:
        return []
    try:
        return tender_db.execute_query(
            """
            SELECT id, contract_reg_number, table_source, status,
                   error_message, created_at, completed_at, worker_id
            FROM document_processing_queue
            WHERE status IN ('error', 'no_links')
            ORDER BY COALESCE(completed_at, created_at) DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        ) or []
    except Exception:
        return []


def get_system_alerts(tender_db, limit: int = 20) -> list[dict]:
    """Возвращает неподтверждённые системные алерты из daemon_alerts."""
    if not tender_db:
        return []
    try:
        return tender_db.execute_query(
            """
            SELECT id, alert_type, message, worker_id, created_at
            FROM daemon_alerts
            WHERE acknowledged = FALSE
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        ) or []
    except Exception:
        return []


def acknowledge_alert(tender_db, alert_id: int) -> bool:
    """Помечает алерт как прочитанный."""
    if not tender_db:
        return False
    try:
        tender_db.execute_query(
            "UPDATE daemon_alerts SET acknowledged = TRUE WHERE id = %s",
            (alert_id,),
        )
        return True
    except Exception:
        return False


def get_worker_logs(lines: int = 80) -> CommandResult:
    return ssh_worker(
        f"journalctl -u {WORKER_SERVICE} -n {int(lines)} --no-pager",
        timeout=20,
    )

