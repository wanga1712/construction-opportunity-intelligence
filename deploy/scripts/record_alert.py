#!/usr/bin/env python3
import sys, psycopg2
msg = sys.argv[1]
conn = psycopg2.connect(host='10.8.0.7', port=5432, dbname='tender_monitor',
                        user='postgres', password='0IFz3_')
cur = conn.cursor()
cur.execute("INSERT INTO daemon_alerts(alert_type,message,worker_id) VALUES('temperature',%s,13)", (msg,))
conn.commit(); conn.close()
