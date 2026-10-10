#!/bin/bash
for U in run-u3357249.service run-u3357149.service; do
  echo "=== $U ==="
  systemctl status "$U" --no-pager 2>&1 | head -12
  echo "--- journal ---"
  journalctl -u "$U" --no-pager 2>&1 | tail -25
done
