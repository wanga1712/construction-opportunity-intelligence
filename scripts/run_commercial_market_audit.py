#!/usr/bin/env python3
"""PHASE 1 runner for the commercial market truth audit (read-only).

WIP=COMMERCIAL_SITE_CRM_LINK_V1.

    python3 scripts/run_commercial_market_audit.py          # CRM audit
    python3 scripts/run_commercial_market_audit.py --di     # + confirmed-fact cross-check

Runs on S13 against the canonical CRM database with the runtime CRM role taken
from `.env`.  Both SQL files are SELECT-only; nothing is written.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.getenv("CRM_ENV_FILE", str(ROOT / ".env")))
SQL_MAIN = ROOT / "scripts" / "commercial_market_audit.sql"
SQL_DI = ROOT / "scripts" / "commercial_market_audit_di_crosscheck.sql"


def env_value(key: str, default: str = "") -> str:
    """Read one key from `.env` without sourcing it (the file has prose lines)."""
    if not ENV_FILE.exists():
        return default
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


def run_psql(dbname: str, user: str, sql_file: Path, password: str,
             host: str, port: str, strict: bool) -> int:
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    cmd = ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname,
           "-v", "ON_ERROR_STOP=%d" % (1 if strict else 0),
           "-At", "-F|", "-f", str(sql_file)]
    return subprocess.run(cmd, env=env, cwd=str(ROOT)).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Commercial market truth audit (read-only)")
    parser.add_argument("--di", action="store_true",
                        help="also cross-check confirmed_category_facts in document_intelligence")
    args = parser.parse_args(argv)

    host = env_value("CRM_DB_HOST", "127.0.0.1")
    port = env_value("CRM_DB_PORT", "5432")
    user = env_value("CRM_DB_USER", "crm_app")
    password = env_value("CRM_DB_PASSWORD")
    dbname = env_value("CRM_DB_DATABASE", "crm")

    rc = run_psql(dbname, user, SQL_MAIN, password, host, port, strict=True)
    if rc != 0:
        return rc
    if not args.di:
        return 0

    di_db = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    di_user = os.getenv("S13_DOCUMENT_DB_USER", user)
    print("=== 11. CONFIRMED FACTS CROSS-CHECK (%s as %s) ===" % (di_db, di_user))
    rc = run_psql(di_db, di_user, SQL_DI, password, host, port, strict=True)
    if rc != 0:
        print("PERMISSION_DENIED_OR_UNAVAILABLE: the runtime role cannot read "
              "confirmed_category_facts (expected for crm_app until "
              "GRANT SELECT ... TO crm_app is approved).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
