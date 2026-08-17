#!/usr/bin/env python3
"""Официальный CRM sync runner (V3 production projection writer).

Запускается вручную или через systemd timer (crm-procurement-sync.timer).

Production path:
  S7 tender_monitor READ ONLY
    → V3 projection / admission
    → S13 crm_procurements WRITE

Legacy sync_all_processed is NOT the production path.

Schema DDL is NOT applied here.
Runtime fails closed if required CRM tables are missing.

Использование:
  PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89 \\
    .venv313/bin/python scripts/run_crm_sync.py
  PYTHONPATH=... .venv313/bin/python scripts/run_crm_sync.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/pythonProject89")

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_crm_sync")

from src.services.crm_procurements_schema import ensure_schema
from src.services.db_bootstrap import connect_databases
from src.services.db_role_contract import resolve_db_role_contract
from src.services.commercial_routing_v3.projection_writer import (
    LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH,
    PRODUCTION_PROJECTION_WRITER,
    run_v3_projection_sync,
)

assert PRODUCTION_PROJECTION_WRITER == "V3"
assert LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH is False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CRM V3 projection sync")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute admission/upsert plan without writing S13",
    )
    args = parser.parse_args(argv)

    radar_db, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning("connect_databases warnings: %s", warn)

    role_contract = resolve_db_role_contract()
    logger.info(
        "DB_ROLE_CONTRACT source=%s crm=%s same_server=%s same_database=%s",
        role_contract.source.route,
        role_contract.crm.route,
        role_contract.same_server,
        role_contract.same_database,
    )
    if role_contract.ambiguous_generic_fallback:
        logger.error("Ambiguous SOURCE/CRM DSN fallback detected — aborting sync")
        return 2
    if role_contract.same_database:
        logger.error("SOURCE and CRM resolve to the same database — aborting sync")
        return 2
    if not tender_db or not crm_db:
        logger.error("SOURCE or CRM DB unavailable — aborting")
        return 1

    if not ensure_schema(crm_db):
        logger.error("CRM schema NOT_READY — aborting sync (no runtime DDL)")
        return 3

    logger.info(
        "Running V3 projection writer (dry_run=%s); legacy sync_all_processed production path=NO",
        args.dry_run,
    )
    result = run_v3_projection_sync(tender_db, crm_db, dry_run=bool(args.dry_run))
    logger.info("Sync result: %s", result)
    print(result)
    return 0 if int(result.get("errors") or 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
