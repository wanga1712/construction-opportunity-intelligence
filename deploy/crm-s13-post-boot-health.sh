#!/bin/bash
# Post-boot / periodic health watchdog for S13.
#
# Goals:
#   * wait for S7 DB/Tailscale before touching services that depend on S7;
#   * start any core CRM/document/kiosk unit that is not running;
#   * on boot, restart factual-feeder and shadow-predictor AFTER S7 is reachable
#     so they never keep a connection opened before the network was ready;
#   * ensure dashboard HTTP is alive and timers are active;
#   * report unplanned queue rows so a stuck queue is visible in journal.

set -uo pipefail

LOG_TAG="crm-s13-post-boot-health"
S7_HOST="${S7_DB_HOST:-100.80.226.124}"
S7_PORT="${S7_DB_PORT:-5432}"
MODE="${1:-check}"

CORE_SERVICES=(
  s13-dashboard3
  s13-kiosk
  crm-streamlit
  tender-docs-daemon-open
  tender-docs-daemon-open-2
  tender-docs-daemon-open-3
  tender-docs-daemon-awarded
  tender-docs-band-gold-1
  tender-docs-band-gold-2
  tender-docs-band-silver
  tender-docs-band-bronze
  tender-docs-band-wood
  crm-v3-autonomous-worker
  crm-v3-learning-observer
)

CORE_TIMERS=(
  crm-procurement-sync.timer
  crm-ai-assessment-runner.timer
  crm-s13-scheduled-suspend.timer
)

log() {
  logger -t "$LOG_TAG" "$*"
  echo "$(date -Is) $*"
}

wait_for_s7() {
  local i
  for i in $(seq 1 60); do
    if nc -z -w2 "$S7_HOST" "$S7_PORT" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

ensure_active() {
  local unit="$1"
  if systemctl is-active --quiet "$unit"; then
    log "OK unit=$unit state=$(systemctl is-active "$unit")"
  else
    log "START unit=$unit was=$(systemctl is-active "$unit" 2>/dev/null || echo missing)"
    systemctl start "$unit" || log "ERROR start unit=$unit"
  fi
}

queue_unplanned_count() {
  runuser -u postgres -- psql -d document_intelligence -At \
    -c "SELECT count(*) FROM document_processing_queue
        WHERE pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
          AND status IN ('PENDING','PRE_RESEARCH_WAITING')
          AND (selected_documents IS NULL
               OR jsonb_typeof(selected_documents) <> 'array'
               OR jsonb_array_length(selected_documents) = 0)" 2>/dev/null
}

main() {
  log "START mode=$MODE"

  if ! wait_for_s7; then
    log "ERROR S7 unreachable after wait host=$S7_HOST port=$S7_PORT"
    exit 1
  fi
  log "S7_REACHABLE=YES"

  for unit in "${CORE_SERVICES[@]}"; do
    ensure_active "$unit"
  done

  for timer in "${CORE_TIMERS[@]}"; do
    systemctl start "$timer" 2>/dev/null || log "WARN timer=$timer"
    log "TIMER timer=$timer active=$(systemctl is-active "$timer" 2>/dev/null || echo missing)"
  done

  if [[ "$MODE" == "boot" ]]; then
    log "BOOT_RESTART feeder/shadow after S7 is reachable"
    systemctl restart crm-v3-factual-feeder.service crm-v3-shadow-predictor.service
  else
    ensure_active crm-v3-factual-feeder.service
    ensure_active crm-v3-shadow-predictor.service
  fi

  if curl -fsS --max-time 8 http://127.0.0.1:8897/api/metrics >/dev/null 2>&1; then
    log "DASHBOARD_HTTP=OK"
  else
    log "DASHBOARD_HTTP=FAIL restarting s13-dashboard3"
    systemctl restart s13-dashboard3.service
  fi

  local unplanned
  unplanned="$(queue_unplanned_count)"
  log "QUEUE_UNPLANNED_ROWS=${unplanned:-unknown}"
  if [[ -n "$unplanned" && "$unplanned" -gt 0 ]]; then
    log "WARN queue has unplanned rows that document workers cannot claim"
  fi

  log "FINISH mode=$MODE"
}

main "$MODE"
