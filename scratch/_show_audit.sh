#!/bin/bash
# usage: bash /tmp/_show_audit.sh <file> [grep-pattern]
F="${1:-/tmp/audit670.txt}"
if [ -n "$2" ]; then
  grep -E "$2" "$F"
else
  grep -E "RAW|COUNTS|AUDIT|LOSSES|TOTALS|COLUMNS" "$F"
  echo "--- product sample ---"
  sed -n '/--- product/,/--- delivery/p' "$F" | head -8
  echo "--- delivery sample ---"
  sed -n '/--- delivery/,/--- participant/p' "$F" | head -8
fi
