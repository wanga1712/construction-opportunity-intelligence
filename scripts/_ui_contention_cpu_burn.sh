#!/usr/bin/env bash
# Synthetic CPU contention on background-allowed CPUs only (2-7).
# Does NOT touch CRM reserved CPUs 0-1.
set -euo pipefail
DURATION="${1:-90}"
# Prefer stress-ng; fallback to busy loops pinned to CPUs 2-7.
if command -v stress-ng >/dev/null 2>&1; then
  exec taskset -c 2-7 stress-ng --cpu 6 --timeout "${DURATION}s" --metrics-brief
fi
pids=()
for c in 2 3 4 5 6 7; do
  taskset -c "$c" bash -c "
    end=\$((SECONDS+${DURATION}))
    while (( SECONDS < end )); do :; done
  " &
  pids+=("$!")
done
wait "${pids[@]}"
