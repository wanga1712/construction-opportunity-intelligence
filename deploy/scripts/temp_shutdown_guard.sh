#!/bin/bash
CRIT=80
DURATION_LIMIT=600
STATE_FILE=/tmp/temp_high_since
LOG=/var/log/temp_monitor.log
PYTHON=/opt/tender_documents_research/.venv/bin/python3

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

CPU_TEMP=$(sensors 2>/dev/null | awk '/Package id 0:/ {gsub(/[^0-9.]/," ",$4); print int($4)}')
CPU_TEMP=${CPU_TEMP:-0}
GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
GPU_TEMP=${GPU_TEMP:-0}
RAM_INFO=$(free -m | awk '/^Память:|^Mem:/ {print $2,$3}')
RAM_TOTAL=$(echo $RAM_INFO | awk '{print $1}')
RAM_USED=$(echo $RAM_INFO | awk '{print $2}')
LOAD1=$(awk '{print $1}' /proc/loadavg)
LOAD5=$(awk '{print $2}' /proc/loadavg)
CPU_PCT=$(top -bn1 | awk '/^%Cpu|^Cpu/ {print int(100-$8)}' 2>/dev/null | head -1)
CPU_PCT=${CPU_PCT:-0}

log "CPU=${CPU_TEMP}°C GPU=${GPU_TEMP}°C RAM=${RAM_USED}/${RAM_TOTAL}MB LOAD=${LOAD1}"

$PYTHON /usr/local/bin/record_metrics.py 13 "$CPU_TEMP" "$GPU_TEMP" "$RAM_USED" "$RAM_TOTAL" "$LOAD1" "$LOAD5" "$CPU_PCT" 2>>$LOG || true

if [ "$CPU_TEMP" -ge "$CRIT" ]; then
  if [ -f "$STATE_FILE" ]; then
    HIGH_SINCE=$(cat "$STATE_FILE")
    ELAPSED=$(( $(date +%s) - HIGH_SINCE ))
    log "CPU >= ${CRIT}°C уже ${ELAPSED}с / порог ${DURATION_LIMIT}с"
    if [ "$ELAPSED" -ge "$DURATION_LIMIT" ]; then
      MSG="АВАРИЯ: CPU ${CPU_TEMP}°C более 10 минут!"
      log "$MSG"
      $PYTHON /usr/local/bin/record_alert.py "$MSG" 2>>$LOG || true
      sleep 2
      /usr/sbin/shutdown -h now "Перегрев CPU ${CPU_TEMP}°C"
    fi
  else
    date +%s > "$STATE_FILE"
    $PYTHON /usr/local/bin/record_alert.py "CPU ${CPU_TEMP}°C — начало отсчёта 10 минут" 2>>$LOG || true
    log "CPU >= ${CRIT}°C — начало отсчёта"
  fi
else
  [ -f "$STATE_FILE" ] && rm -f "$STATE_FILE" && log "CPU норма (${CPU_TEMP}°C)"
fi
