#!/usr/bin/env python3
"""Record server metrics. Credentials come from runtime env only."""
import os
import sys

import psycopg2


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    _, server_id, cpu_temp, gpu_temp, ram_used, ram_total, load1, load5, cpu_pct = sys.argv
    conn = psycopg2.connect(
        host=_require("TENDER_MONITOR_DB_HOST"),
        port=int(_require("TENDER_MONITOR_DB_PORT")),
        dbname=_require("TENDER_MONITOR_DB_DATABASE"),
        user=_require("TENDER_MONITOR_DB_USER"),
        password=_require("TENDER_MONITOR_DB_PASSWORD"),
    )
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO server_metrics(server_id,cpu_temp,gpu_temp,ram_used_mb,ram_total_mb,load_1min,load_5min,cpu_pct) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            int(server_id),
            int(float(cpu_temp)),
            int(float(gpu_temp)),
            int(float(ram_used)),
            int(float(ram_total)),
            float(load1),
            float(load5),
            int(float(cpu_pct)),
        ),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
