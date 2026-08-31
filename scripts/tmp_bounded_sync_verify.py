#!/usr/bin/env python3
"""Bounded Sync Verification Script.

Pulls and verifies 4 specific canaries:
1. 44-FZ normal path
2. Current 223-FZ normal path
3. Recovered legacy 223-FZ
4. Unrecoverable legacy 223-FZ (including 32615712992)
"""
from __future__ import annotations

import sys
import logging
from datetime import datetime, timezone, date

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/pythonProject89")

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.projection_writer import _upsert_one
from src.services.commercial_routing_v3.projection import resolve_lifecycle_identity
from src.services.torgi_publication import source_lifecycle_allows_torgi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bounded_verify")


def fetch_source_row(tender_db, table: str, contract_number: str) -> dict | None:
    import psycopg2.extras
    cust_col = "placer" if "223" in table else "customer"
    conn = tender_db.get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT
                c.id AS source_id,
                c.contract_number,
                c.auction_name,
                c.initial_price,
                c.final_price,
                c.{cust_col} AS customer,
                c.start_date,
                c.end_date,
                c.delivery_start_date,
                c.delivery_end_date,
                c.tender_link,
                c.updated_at AS source_updated_at,
                c.created_at AS source_created_at,
                c.customer_id AS source_customer_id,
                c.region_id,
                COALESCE(NULLIF(btrim(c.delivery_region), ''), r.name) AS delivery_region,
                c.delivery_address,
                c.okpd_id AS source_okpd_id,
                o.sub_code AS okpd_code,
                o.name AS okpd_name
            FROM {table} c
            LEFT JOIN collection_codes_okpd o ON o.id = c.okpd_id
            LEFT JOIN region r ON r.id = c.region_id
            WHERE c.contract_number = %s
            LIMIT 1
        """, (contract_number,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)


def get_existing_crm(crm_db, table: str, source_id: int) -> dict | None:
    rows = crm_db.execute_query("""
        SELECT id, source_table, source_id, contract_number, crm_stage,
               award_status, end_date, deadline_trust
        FROM crm_procurements
        WHERE source_table = %s AND source_id = %s
        LIMIT 1
    """, (table, source_id))
    if not rows:
        return None
    return rows[0]


def main() -> int:
    _, tender_db, crm_db, _ = connect_databases()
    if not tender_db or not crm_db:
        logger.error("Database connection failed")
        return 1

    # Canaries list
    canaries = [
        # 1. Unrecoverable legacy 223-FZ (including 32615712992)
        ("reestr_contract_223_fz", "32615712992", "UNRECOVERABLE_LEGACY"),
        # 2. Recovered legacy 223-FZ
        ("reestr_contract_223_fz", "32616242613", "RECOVERED"),
        # 3. Current 223-FZ
        ("reestr_contract_223_fz", "32616290167", "TRUSTED"),
        # 4. Normal 44-FZ
        ("reestr_contract_44_fz", "0373200275826000001", "TRUSTED"),
    ]

    errors = 0

    for table, cn, expected_trust in canaries:
        logger.info("=== Verifying %s / %s (Expected trust: %s) ===", table, cn, expected_trust)
        row = fetch_source_row(tender_db, table, cn)
        if not row:
            logger.error("Source row %s / %s not found in tender_db!", table, cn)
            errors += 1
            continue

        row["source_table"] = table
        existing = get_existing_crm(crm_db, table, row["source_id"])

        # Execute Upsert in dry_run mode first
        action_dry = _upsert_one(crm_db, row, existing, dry_run=True)
        logger.info("Dry run action: %s", action_dry)

        # Execute Upsert in actual mode
        action_live = _upsert_one(crm_db, row, existing, dry_run=False)
        logger.info("Live run action: %s", action_live)

        # Fetch from S13 and verify results
        updated_crm = get_existing_crm(crm_db, table, row["source_id"])
        if not updated_crm:
            logger.error("CRM row not found in S13 after sync!")
            errors += 1
            continue

        logger.info("Synced crm row: %s", updated_crm)

        # Check deadline_trust
        if updated_crm["deadline_trust"] != expected_trust:
            logger.error("deadline_trust MISMATCH! Got: %s, Expected: %s", updated_crm["deadline_trust"], expected_trust)
            errors += 1

        # Specific checks for UNRECOVERABLE_LEGACY
        if expected_trust == "UNRECOVERABLE_LEGACY":
            if updated_crm["end_date"] is not None:
                logger.error("Unrecoverable legacy canary end_date is NOT NULL! Got: %s", updated_crm["end_date"])
                errors += 1
            if updated_crm["crm_stage"] != "torgi":
                logger.error("Unrecoverable legacy canary stage is not torgi! Got: %s", updated_crm["crm_stage"])
                errors += 1
            if updated_crm["award_status"] != "submission_closed_waiting_award":
                logger.error("Unrecoverable legacy canary award_status is not closed! Got: %s", updated_crm["award_status"])
                errors += 1

            # Verify it is not active in torgi
            allowed = source_lifecycle_allows_torgi(
                crm_stage=updated_crm["crm_stage"],
                award_status=updated_crm["award_status"],
                end_date=updated_crm["end_date"],
                today=date.today()
            )
            if allowed:
                logger.error("Unrecoverable legacy canary IS ACTIVE IN TORGI lifecycle!")
                errors += 1
            else:
                logger.info("Unrecoverable legacy canary IS NOT ACTIVE IN TORGI (Correct)")

    logger.info("Verification completed. Errors: %d", errors)
    return errors


if __name__ == "__main__":
    sys.exit(main())
