#!/bin/bash
echo "--- run units ---"
systemctl list-units 'run-*' --no-legend --plain 2>/dev/null | head -5
echo "--- force processes ---"
ps -eo pid,etimes,stat,cmd | grep -E "force_direct|document_processor" | grep -v grep | head -10
echo "--- last logs of the newest run unit ---"
UNIT=$(systemctl list-units 'run-*' --no-legend --plain 2>/dev/null | awk '{print $1}' | head -1)
echo "unit=$UNIT"
[ -n "$UNIT" ] && journalctl -u "$UNIT" --no-pager | tail -30
