#!/bin/bash
# S13 visual console dashboard on the physical screen (tty1). ASCII-safe + ANSI color.
export TERM="${TERM:-linux}"; export LANG=C.UTF-8
ONETIME=0; [ "${1:-}" = "--once" ] && ONETIME=1
INTERVAL=5; HIST=""; HISTN=0
E=$'\033'; RST="${E}[0m"; BOLD="${E}[1m"; DIM="${E}[2m"
G="${E}[32m"; Y="${E}[33m"; R="${E}[31m"; C="${E}[36m"; M="${E}[35m"

svc() { systemctl is-active "$1" 2>/dev/null | tr -d '\n'; }
dot() { if [ "$1" = "active" ]; then printf "%s*%s" "$G" "$RST"; else printf "%sx%s" "$R" "$RST"; fi; }
col() { local p=$1; if [ "$p" -ge 85 ]; then printf "%s" "$R"; elif [ "$p" -ge 70 ]; then printf "%s" "$Y"; else printf "%s" "$G"; fi; }
bar() {
  local p=$1 w=$2 f e
  [ -z "$p" ] && p=0; [ "$p" -lt 0 ] 2>/dev/null && p=0; [ "$p" -gt 100 ] 2>/dev/null && p=100
  f=$(( p * w / 100 )); e=$(( w - f ))
  printf '%s' "$(col "$p")"; printf '%*s' "$f" '' | tr ' ' '#'
  printf '%s' "$DIM"; printf '%*s' "$e" '' | tr ' ' '.'
  printf '%s' "$RST"
}
spark() { local chars=" .:-=+*#%@" out="" v idx; for v in $HIST; do idx=$(( v * 9 / 100 )); out="${out}${chars:$idx:1}"; done; printf '%s' "$out"; }
vt_assert() { local a; a=$(cat /sys/class/tty/tty0/active 2>/dev/null); if [ "$a" != "tty1" ] && { [ "$a" = "tty7" ] || [ -z "$a" ]; }; then chvt 1 2>/dev/null || true; fi; }

render() {
  printf '%s[2J%s[H' "$E" "$E"
  local u n s idle w irq sirq st _ t1 t2 i1 i2 busy pkg
  read -r _ u n s idle w irq sirq st _ < /proc/stat; t1=$((u+n+s+idle+w+irq+sirq+st)); i1=$idle
  sleep 1
  read -r _ u n s idle w irq sirq st _ < /proc/stat; t2=$((u+n+s+idle+w+irq+sirq+st)); i2=$idle
  busy=$((100-100*(i2-i1)/(t2-t1)))
  HIST="${HIST} ${busy}"; HISTN=$((HISTN+1)); [ "$HISTN" -gt 64 ] && HIST=$(echo "$HIST" | awk '{for(i=2;i<=NF;i++)printf "%s ",$i}')
  pkg=$(sensors 2>/dev/null | awk '/Package id 0:/{gsub(/[^0-9.]/," ",$4);print int($4)}'); [ -z "$pkg" ] && pkg=0

  local host up load ramu ramt rama swapu swapt ramp swapp
  host=$(hostname); up=$(uptime -p 2>/dev/null | sed 's/^up //'); load=$(cut -d' ' -f1-3 /proc/loadavg)
  read -r ramu ramt rama < <(awk '/^MemTotal:/{t=$2}/^MemAvailable:/{a=$2}END{printf "%.1f %.1f %.1f",(t-a)/1048576,t/1048576,a/1048576}' /proc/meminfo)
  read -r swapu swapt < <(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{printf "%.1f %.1f",(t-f)/1048576,t/1048576}' /proc/meminfo)
  ramp=$(( ${ramu%.*} * 100 / ${ramt%.*} )); swapp=0; [ "${swapt%.*}" -gt 0 ] && swapp=$(( ${swapu%.*} * 100 / ${swapt%.*} ))

  printf '%s%s===================== S13: %s =====================%s\n' "$C" "$BOLD" "$host" "$RST"
  printf ' %s   up %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$up"
  printf '%sCPU history (last %s):%s %s%s%s\n' "$DIM" "$HISTN" "$RST" "$C" "$(spark)" "$RST"
  printf ' CPU  [%s] %s%3s%%%s  %s%3s C%s   load %s\n' "$(bar "$busy" 30)" "$(col "$busy")" "$busy" "$RST" "$(col "$pkg")" "$pkg" "$RST" "$load"
  printf ' RAM  [%s] %s%3s%%%s  %sG / %sG  avail %sG\n' "$(bar "$ramp" 30)" "$(col "$ramp")" "$ramp" "$RST" "$ramu" "$ramt" "$rama"
  printf ' SWAP [%s] %s%3s%%%s  %sG / %sG\n' "$(bar "$swapp" 30)" "$(col "$swapp")" "$swapp" "$RST" "$swapu" "$swapt"

  printf '%s---------------------------- GPU ----------------------------%s\n' "$M" "$RST"
  local g; g=$(nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu --format=csv,noheader,nounits 2>/dev/null)
  if [ -n "$g" ]; then
    local gu gmu gmt gpw gpl gt gv; IFS=', ' read -r gu gmu gmt gpw gpl gt <<< "$g"; gv=$(( gmu * 100 / gmt ))
    printf ' GPU  [%s] %s%3s%%%s  %sW/%sW  %s C\n' "$(bar "$gu" 30)" "$(col "$gu")" "$gu" "$RST" "${gpw%.*}" "${gpl%.*}" "$gt"
    printf ' VRAM [%s] %s%3s%%%s  %s / %s MiB\n' "$(bar "$gv" 30)" "$(col "$gv")" "$gv" "$RST" "$gmu" "$gmt"
  else printf ' GPU n/a\n'; fi

  printf '%s--------------------------- DISK ----------------------------%s\n' "$M" "$RST"
  for m in / /data; do
    read -r sz us av pc < <(df -h "$m" 2>/dev/null | awk 'NR==2{gsub("%","",$5);print $2,$3,$4,$5}')
    [ -z "$pc" ] && continue
    printf ' %-6s[%s] %s%3s%%%s  %s used / %s (avail %s)\n' "$m" "$(bar "$pc" 30)" "$(col "$pc")" "$pc" "$RST" "$us" "$sz" "$av"
  done

  printf '%s------------------------- SERVICES --------------------------%s\n' "$M" "$RST"
  printf ' %s CRM%s   %s ollama%s   %s postgres%s   %s health%s   http %s\n' \
    "$(dot "$(svc crm-streamlit.service)")" "$RST" "$(dot "$(svc ollama.service)")" "$RST" \
    "$(dot "$(svc postgresql@17-main.service)")" "$RST" "$(dot "$(svc crm-system-health-collector.service)")" "$RST" \
    "$(curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 5 http://127.0.0.1:8504/ 2>/dev/null)"
  printf ' docs  %s gold1  %s gold2  %s silver  %s bronze  %s wood\n' \
    "$(dot "$(svc tender-docs-band-gold-1.service)")" "$(dot "$(svc tender-docs-band-gold-2.service)")" \
    "$(dot "$(svc tender-docs-band-silver.service)")" "$(dot "$(svc tender-docs-band-bronze.service)")" "$(dot "$(svc tender-docs-band-wood.service)")"

  printf '%s-------------------------- QUEUE ---------------------------%s\n' "$M" "$RST"
  local q band cnt cap
  q=$(timeout 8 runuser -u postgres -- psql -d document_intelligence -At -F'|' \
    -c "SELECT COALESCE(research_prior_band,'UNSCORED'), count(*) FROM document_processing_queue WHERE status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING') GROUP BY 1 ORDER BY 1" 2>/dev/null)
  if [ -z "$q" ]; then echo " (queue n/a)"; else
    while IFS='|' read -r band cnt; do
      [ -z "$band" ] && continue; cap=$cnt; [ "$cap" -gt 80 ] && cap=80
      printf ' %-9s[%s] %s\n' "$band" "$(bar "$(( cap * 100 / 80 ))" 30)" "$cnt"
    done <<< "$q"
  fi

  printf '%s------------------------- TOP CPU --------------------------%s\n' "$M" "$RST"
  ps -eo pcpu,comm --sort=-pcpu | awk 'NR>1 && $2!="ps" && $2!="s13_dashboard.sh"{printf " %5s%%  %s\n",$1,$2; n++} n>=5{exit}'
  printf '%s(refresh %ss)%s\n' "$DIM" "$INTERVAL" "$RST"
}

while :; do vt_assert; render; [ "$ONETIME" = "1" ] && break; sleep "$INTERVAL"; done
