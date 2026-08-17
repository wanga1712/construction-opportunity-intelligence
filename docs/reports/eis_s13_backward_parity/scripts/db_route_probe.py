#!/usr/bin/env python3
"""Probe S13 backward DB route. Prints host/db/role only."""
from pathlib import Path
import os
import psycopg2

env = {}
for line in Path("/opt/tendermonitor/database_work/db_credintials.env").read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()

host = env["DB_HOST_TENDER"]
port = env.get("DB_PORT_TENDER", "5432")
name = env["DB_DATABASE_TENDER"]
user = env["DB_USER_TENDER"]
conn = psycopg2.connect(
    host=host,
    port=port,
    dbname=name,
    user=user,
    password=env["DB_PASSWORD_TENDER"],
    connect_timeout=10,
)
cur = conn.cursor()
cur.execute("SELECT inet_server_addr()::text, inet_server_port(), current_database(), current_user")
row = cur.fetchall()[0]
print("BACKWARD_DB_HOST_CONFIG=" + host)
print("BACKWARD_DB_PORT=" + str(port))
print("BACKWARD_DB_NAME=" + name)
print("BACKWARD_DB_ROLE=" + user)
print("CONNECTED_SERVER_ADDR=" + str(row[0]))
print("CONNECTED_SERVER_PORT=" + str(row[1]))
print("CONNECTED_DB=" + str(row[2]))
print("CONNECTED_USER=" + str(row[3]))
expected = os.environ.get("S7_DB_HOST", "")
print(
    "S13_TO_S7_DB_CONNECTION=OK"
    if expected and host == expected
    else "S13_TO_S7_DB_CONNECTION=UNEXPECTED_HOST"
)
conn.close()
