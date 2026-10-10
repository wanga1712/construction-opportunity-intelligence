#!/bin/bash
for PID in 459924 459631 459670; do
  echo "=== pid $PID ==="
  CARD_PID="$PID" bash /tmp/_run_py.sh /tmp/_card_audit_probe.py 2>/dev/null > /tmp/audit_$PID.txt
  grep -E "RAW:|COUNTS:|LOSSES:" /tmp/audit_$PID.txt
  sed -n '/--- product (/,+4p' /tmp/audit_$PID.txt | head -5
done
