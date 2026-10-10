"""Проверка новой отрисовки медали (подтверждённая + пометка окна)."""
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.analytics_table_workspace_service import load_workspace_rows
from src.services.db_bootstrap import connect_databases
from src.ui.analytics_table_workspace_page import _medal_cell

_r, _t, crm_db, _w = connect_databases()
result = load_workspace_rows(crm_db, selected_mode="DIRECT_SUPPLY", only_active=False)
rows = result.get("rows") or []
interest = [459631, 459670, 459671]
for pid in interest:
    row = next((r for r in rows if r.get("procurement_id") == pid), None)
    if not row:
        print("pid=%s нет строки" % pid)
        continue
    print("pid=%s confirmed=%s current=%s -> %s" % (
        pid, row.get("medal_confirmed"), row.get("medal_current"),
        _medal_cell(row).replace("\n", " ")[:160]))
print("первые 12 групп страницы 1:")
seen = []
for row in rows:
    pid = row.get("procurement_id")
    if pid in seen:
        continue
    seen.append(pid)
    if len(seen) > 12:
        break
    print("   pid=%-8s %-8s %s" % (pid, row.get("medal_confirmed") or row.get("medal_current"),
                                   str(row.get("purchase_title") or "")[:60]))
