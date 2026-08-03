#!/usr/bin/env python3
import sys, psycopg2
_, server_id, cpu_temp, gpu_temp, ram_used, ram_total, load1, load5, cpu_pct = sys.argv
conn = psycopg2.connect(host='S7', port=5432, dbname='tender_monitor',
                        user='postgres', password='<REMOVED_COMPROMISED_CREDENTIAL>')
cur = conn.cursor()
cur.execute(
    'INSERT INTO server_metrics(server_id,cpu_temp,gpu_temp,ram_used_mb,ram_total_mb,load_1min,load_5min,cpu_pct) '
    'VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
    (int(server_id), int(float(cpu_temp)), int(float(gpu_temp)), int(float(ram_used)),
     int(float(ram_total)), float(load1), float(load5), int(float(cpu_pct)))
)
conn.commit(); conn.close()
