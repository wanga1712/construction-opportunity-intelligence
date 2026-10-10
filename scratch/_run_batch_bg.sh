#!/bin/bash
# usage: bash /tmp/_run_batch_bg.sh <outfile>
OUT="${1:-/tmp/batch_bg.txt}"
cd /opt/CRM_Streamlit
nohup setsid bash /tmp/_run_py.sh /tmp/_direct_batch_report.py > "$OUT" 2>&1 &
echo "started pid=$! out=$OUT"
