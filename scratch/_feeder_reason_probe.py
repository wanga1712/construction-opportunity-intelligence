"""Почему 456559 не попала в очередь: проверяем условия фидера и её место в выборке."""
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

PID = 456559
KW = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(**KW)
try:
    cur = conn.cursor()
    cur.execute("select id, source_table, crm_stage, award_status, end_date, start_date, contract_number from crm_procurements where id=%s", (PID,))
    print("закупка:", cur.fetchone())

    base = """
        FROM crm_procurements p
        WHERE p.source_table IN ('reestr_contract_44_fz', 'reestr_contract_223_fz')
          AND p.crm_stage = 'torgi'
          AND p.award_status = 'submission_open'
          AND p.end_date >= CURRENT_DATE + INTERVAL '2 days'
    """
    cur.execute("select count(*) " + base)
    total = cur.fetchone()[0]
    print("всего подходящих под условия фидера:", total)
    cur.execute("select count(*) from (select p.id " + base + " order by p.id desc limit 1000) t")
    in_window = cur.fetchone()[0]
    print("из них попадает в окно выборки (LIMIT 1000, ORDER BY id DESC):", in_window)
    cur.execute("select max(p.id), min(p.id) from (select p.id " + base + " order by p.id desc limit 1000) t, crm_procurements p where p.id = t.id")
    print("диапазон id в окне:", cur.fetchone())
    cur.execute("select count(*) " + base + " and p.id > %s", (PID,))
    newer = cur.fetchone()[0]
    print("закупок новее (id > %s) в этом наборе: %s → позиция %s" % (PID, newer, newer + 1))
    cur.execute("select count(*) from crm_procurements p where p.crm_stage='torgi' and coalesce(p.award_status,'') <> 'submission_open' and p.end_date >= CURRENT_DATE")
    print("torgi с end_date в будущем, но award_status НЕ submission_open:", cur.fetchone()[0])
    cur.execute("select coalesce(award_status,'(null)'), count(*) from crm_procurements where crm_stage='torgi' group by 1 order by 2 desc limit 8")
    print("распределение award_status при crm_stage='torgi':")
    for row in cur.fetchall():
        print("   %-24s %s" % row)
finally:
    conn.close()
