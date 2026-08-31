#!/usr/bin/env python3
"""S7 Legacy 223-FZ Contract Recovery Script.

This script executes targeted recovery of 223-FZ contract details from the EIS SOAP API.
Instead of doing a full range search, it queries the S7 tender_monitor database to find the
exact dates and regions of the contracts parsed during the affected period (pre 2026-08-16)
and fetches their XML notices.
"""
from __future__ import annotations

import sys
import os
from collections import defaultdict

# Force the S7 parser to re-parse and overwrite legacy rows with true deadlines
os.environ["FORCE_REPARSE_LEGACY"] = "1"

# S7 production paths
sys.path.insert(0, '/opt/tendermonitor')

from database_work.database_connection import DatabaseManager
from eis_requester import EISRequester


def main() -> None:
    print("Querying S7 database for legacy date/region distribution...")
    db = DatabaseManager()
    date_regions = defaultdict(list)

    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT c.created_at::date::text as date_str, r.code as region_code
            FROM reestr_contract_223_fz c
            JOIN region r ON r.id = c.region_id
            WHERE c.created_at < '2026-08-16 00:00:00'::timestamp
            ORDER BY 1, 2;
        """)
        rows = cursor.fetchall()
        for row in rows:
            date_str = row[0]
            region_code = str(row[1])
            date_regions[date_str].append(region_code)

    total_scans = sum(len(regs) for regs in date_regions.values())
    print(f"Found {len(date_regions)} unique dates with total {total_scans} date/region targets.")
    print("Starting optimized legacy 223-FZ recovery...")

    for d in sorted(date_regions.keys()):
        regions = date_regions[d]
        print(f"\n=== Processing Date: {d} | Regions to scan: {regions} ===")
        req = EISRequester(date=d)
        req.regions = regions
        req.subsystems_44 = []
        req.subsystems_223 = ["RI223"]
        req.process_requests()

    print("\nRecovery finished successfully!")


if __name__ == "__main__":
    main()
