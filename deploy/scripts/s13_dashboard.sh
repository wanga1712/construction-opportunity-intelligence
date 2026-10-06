#!/bin/bash
# S13 console dashboard: server parameters on the physical screen (tty1).
export TERM="${TERM:-linux}"
export LANG=C.UTF-8
ONETIME=0
[ "${1:-}" = "--once" ] && ONETIME=1
INTERVAL=5

svc() { systemctl is-active "$1" 2>/dev/null | tr -d '\n'; }

vt_assert() {
  # Keep the physical screen on tty1 (unless an operator deliberately sits on tty2-6).
  local a; a=$(cat /sys/class/tty/tty0/active 2>/dev/null)
  if [ "$a" != "tty1" ] && { [ "$a" = "tty7" ] || [ -z "$a" ]; }; then
    chvt 1 2>/dev/null || true
  fi
}

render() {
  printf '\033[2J\033[H'
  local ts up busy pkg
  ts=$(date '+%Y-%m-%d %H:%M:%S'); up=$(uptime -p 2>/dev/null | sed 's/^up //')
  read -r _ u n s idle w irq sirq st _ < /proc/stat; t1=$((u+n+s+idle+w+irq+sirq+st)); i1=$idle
  sleep 1
  read -r _ u n s idle w irq sirq st _ < /proc/stat; t2=$((u+n+s+idle+w+irq+sirq+st)); i2=$idle
  busy=$((100-100*(i2-i1)/(t2-t1)))
  pkg=$(sensors 2>/dev/null | awk '/Package id 0:/{gsub(/[^0-9.]/," ",$4);print int($4)}')
  echo "=================== $(hostname) ==================="
  echo " time : $ts          uptime: $up"
  echo " load : $(cut -d' ' -f1-3 /proc/loadavg)"
  echo " CPU  : ${busy}% busy   temp: ${pkg} C"
  echo " RAM  : $(awk '/^MemTotal:/{t=$2}/^MemAvailable:/{a=$2}END{printf "%.1fG used / %.1fG total, %.1fG avail",(t-a)/1048576,t/1048576,a/1048576}' /proc/meminfo)"
  echo " SWAP : $(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{printf "%.1fG / %.1fG",(t-f)/1048576,t/1048576}' /proc/meminfo)"
  echo "------------------- GPU (NVIDIA) -------------------"
  nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu --format=csv,noheader,nounits 2>/dev/null | \
    awk -F', ' '{printf " util %s%% | VRAM %s/%s MiB | %s/%s W | %s C\n",$1,$2,$3,$4,$5,$6}' || echo " n/a"
  echo "---------------------- DISK ------------------------"
  df -h / /data 2>/dev/null | awk 'NR==1{print " mount        size used avail use%"} NR>1{printf " %-12s %s %s %s %s\n",$6,$2,$3,$4,$5}'
  echo "-------------------- SERVICES ----------------------"
  printf " CRM=%s ollama=%s postgres=%s health=%s\n" "$(svc crm-streamlit.service)" "$(svc ollama.service)" "$(svc postgresql@17-main.service)" "$(svc crm-system-health-collector.service)"
  printf " docs: gold1=%s gold2=%s silver=%s bronze=%s wood=%s\n" "$(svc tender-docs-band-gold-1.service)" "$(svc tender-docs-band-gold-2.service)" "$(svc tender-docs-band-silver.service)" "$(svc tender-docs-band-bronze.service)" "$(svc tender-docs-band-wood.service)"
  printf " CRM http: %s (%ss)\n" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8504/ 2>/dev/null)" "$(curl -s -o /dev/null -w '%{time_total}' --max-time 5 http://127.0.0.1:8504/ 2>/dev/null)"
  echo "---------------- QUEUE (document_intelligence) -----"
  timeout 8 runuser -u postgres -- psql -d document_intelligence -At -F'|' \
    -c "SELECT COALESCE(research_prior_band,'UNSCORED')||'='||count(*) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING') GROUP BY COALESCE(research_prior_band,'UNSCORED') ORDER BY 1" 2>/dev/null | tr '\n' ' '
  echo
  echo "--------------------- TOP CPU ----------------------"
  ps -eo pcpu,pmem,comm --sort=-pcpu | head -6 | awk 'NR==1{print " %CPU %MEM COMMAND"} NR>1{printf " %5s %5s %s\n",$1,$2,$3}'
  echo
  echo "(auto-refresh ${INTERVAL}s)"
}

while :; do
  vt_assert
  render
  [ "$ONETIME" = "1" ] && break
  sleep "$INTERVAL"
done
