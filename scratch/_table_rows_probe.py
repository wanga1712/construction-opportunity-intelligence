"""Что реально возвращает витрина по закупкам «Поставка …» (медаль, окно, бакет)."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.analytics_table_workspace_service import load_workspace_rows
from src.services.db_bootstrap import connect_databases

_r, _t, crm_db, _w = connect_databases()
PIDS = [459670, 459671, 459675, 459722, 459888, 459917, 459920, 459924, 460267, 459631]

for mode in ("DIRECT_SUPPLY", "ALL"):
    try:
        result = load_workspace_rows(crm_db, mode=mode, only_active=False)
    except TypeError:
        result = load_workspace_rows(crm_db, selected_mode=mode, only_active=False)
    rows = result.get("rows") or []
    print("=== mode=%s rows=%d ===" % (mode, len(rows)))
    by_pid = {r.get("procurement_id"): r for r in rows}
    for pid in PIDS:
        row = by_pid.get(pid)
        if not row:
            print("   pid=%-8s НЕТ строки" % pid)
            continue
        temporal = row.get("temporal") or {}
        print("   pid=%-8s medal=%-8s from=%-8s bucket=%-14s basis=%-9s ratio=%s" % (
            pid, row.get("medal_current"), row.get("medal_capped_from"),
            temporal.get("temporal_bucket"), temporal.get("window_basis"),
            temporal.get("ratio")))
    break
