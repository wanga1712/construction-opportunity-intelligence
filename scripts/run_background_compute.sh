#!/usr/bin/env bash
# Run one-off heavy AI/eval jobs inside crm-background-compute.slice.
# Usage: run_background_compute.sh -- <command> [args...]
set -euo pipefail

SLICE="${CRM_BACKGROUND_SLICE:-crm-background-compute.slice}"

if [[ "${1:-}" == "--" ]]; then
  shift
fi
if [[ "$#" -lt 1 ]]; then
  echo "usage: $0 -- <command> [args...]" >&2
  exit 2
fi

CWD="${CRM_BACKGROUND_CWD:-/opt/CRM_Streamlit}"
PP="${PYTHONPATH:-/opt/CRM_Streamlit:/opt/pythonProject89}"

# System slice requires privileged systemd-run; prefer passwordless sudo -n.
if sudo -n true 2>/dev/null; then
  exec sudo -n systemd-run \
    --uid="$(id -u)" \
    --gid="$(id -g)" \
    --working-directory="$CWD" \
    --slice="$SLICE" \
    --property=CPUWeight=50 \
    --property=IOWeight=50 \
    --property=Nice=5 \
    --setenv=PYTHONPATH="$PP" \
    --collect \
    -- \
    "$@"
fi

echo "ERROR: sudo -n required to place jobs in $SLICE" >&2
exit 1
