"""Что реально стоит за фильтром «Тип»: сколько закупок в каждом режиме."""
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.analytics_table_workspace_service import (
    ALL_MODES, DESIGN, DIRECT_SUPPLY, EMBEDDED_MATERIAL, OBJECT, load_workspace_rows,
)
from src.services.db_bootstrap import connect_databases

kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(**kw)
try:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT coalesce(opportunity_track,'(null)'), count(*)
               FROM crm_procurement_category_opportunities GROUP BY 1 ORDER BY 2 DESC"""
        )
        print("--- opportunity_track в БД ---")
        for track, count in cur.fetchall():
            print("   %-20s %s" % (track, count))
finally:
    conn.close()

_r, _t, crm_db, _w = connect_databases()
MODES = ((ALL_MODES, "Все"), (DIRECT_SUPPLY, "Прямая поставка"),
         (EMBEDDED_MATERIAL, "В составе работ"), (DESIGN, "Проект"),
         (OBJECT, "Объект (старый тип)"))
for mode, label in MODES:
    result = load_workspace_rows(crm_db, selected_mode=mode, only_active=True, limit=5000)
    rows = result.get("rows") or []
    pids = {r.get("procurement_id") for r in rows}
    print("%-22s строк=%-5d закупок=%-5d" % (label, len(rows), len(pids)))
