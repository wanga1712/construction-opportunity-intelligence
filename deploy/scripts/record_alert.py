#!/usr/bin/env python3
"""Record a temperature alert. Credentials come from runtime env only."""
import os
import sys

import psycopg2


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    msg = sys.argv[1]
    conn = psycopg2.connect(
        host=_require("TENDER_MONITOR_DB_HOST"),
        port=int(_require("TENDER_MONITOR_DB_PORT")),
        dbname=_require("TENDER_MONITOR_DB_DATABASE"),
        user=_require("TENDER_MONITOR_DB_USER"),
        password=_require("TENDER_MONITOR_DB_PASSWORD"),
    )
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO daemon_alerts(alert_type,message,worker_id) VALUES('temperature',%s,13)",
        (msg,),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
