#!/usr/bin/bash
set -euo pipefail
LOG=/var/log/weekend-safety-guard.log
ts(){ date '+%Y-%m-%d %H:%M:%S'; }
log(){ echo "$(ts) $*" | tee -a "$LOG"; }

MIN_MEM_MB=800
MIN_DISK_PCT=5
MAX_LOAD=24

mem_avail=$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
disk_free_pct=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print 100-$5}')
load1=$(awk '{print int($1+0.5)}' /proc/loadavg)

open_state=$(systemctl is-active tender-docs-daemon-open.service 2>/dev/null || echo dead)
awarded_state=$(systemctl is-active tender-docs-daemon-awarded.service 2>/dev/null || echo dead)
legacy_state=$(systemctl is-active tender-docs-daemon.service 2>/dev/null || echo inactive)

if [ "$open_state" = "active" ] && [ "$awarded_state" = "active" ]; then
  daemon_state="active"
elif [ "$legacy_state" = "active" ]; then
  daemon_state="active"
else
  daemon_state="open=${open_state};awarded=${awarded_state};legacy=${legacy_state}"
fi

reason=""
if [ "$mem_avail" -lt "$MIN_MEM_MB" ]; then reason="low_memory avail=${mem_avail}MB"; fi
if [ "$disk_free_pct" -lt "$MIN_DISK_PCT" ]; then reason="${reason:+$reason; }disk_free=${disk_free_pct}%"; fi
if [ "$load1" -gt "$MAX_LOAD" ]; then reason="${reason:+$reason; }load=${load1}"; fi
if [ "$daemon_state" != "active" ]; then reason="${reason:+$reason; }daemon=$daemon_state"; fi

log "check mem=${mem_avail}MB disk_free=${disk_free_pct}% load=${load1} daemon=${daemon_state}"

if [ -n "$reason" ]; then
  log "CRITICAL: $reason — stopping services (NO auto-shutdown)"
  sudo systemctl stop tender-docs-daemon tender-docs-daemon-open tender-docs-daemon-awarded 2>/dev/null || true
  exit 2
fi
exit 0
