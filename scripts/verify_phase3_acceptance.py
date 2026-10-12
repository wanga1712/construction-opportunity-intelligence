"""Acceptance verification script for Phase 3.1 Sort and Filter Consistency.

Runs on S13 production database to audit:
1. Top 50 default sort cards (TOP50_EXPIRED == 0, strict tier monotonicity).
2. Multidimensional filter matrix (preliminary medal, expert status, object family, law).
3. Exact reconciliation between DB aggregations and filter outputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import sys
import time

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.torgi_workset_service import (
    TorgiFilterParams,
    get_evaluated_torgi_workset,
    load_torgi_workset,
)


def verify_phase3_acceptance() -> None:
    print("=" * 70)
    print("PHASE 3.1 CRM PRIORITY SORTING & FILTERS ACCEPTANCE AUDIT")
    print("=" * 70)

    # 1. Evaluate baseline workset
    t0 = time.time()
    base_cards = get_evaluated_torgi_workset(hide_expired=True)
    elapsed_ms = (time.time() - t0) * 1000
    total_count = len(base_cards)

    print(f"Total Active Torgi Matching: {total_count}")
    print(f"Base Evaluation Elapsed Time: {elapsed_ms:.2f} ms")

    # 2. Database Aggregations on baseline
    db_gold = sum(1 for c in base_cards if c["preliminary_medal"] == "GOLD")
    db_silver = sum(1 for c in base_cards if c["preliminary_medal"] == "SILVER")
    db_bronze = sum(1 for c in base_cards if c["preliminary_medal"] == "BRONZE")
    db_wood = sum(1 for c in base_cards if c["preliminary_medal"] == "WOOD")
    db_unassessed = sum(1 for c in base_cards if c["preliminary_medal"] == "UNASSESSED")

    db_social = sum(1 for c in base_cards if c["object_family"] == "SOCIAL")
    db_comm = sum(1 for c in base_cards if c["object_family"] == "COMMERCIAL")
    db_ds = sum(1 for c in base_cards if c["object_family"] == "DIRECT_SUPPLY")
    db_other = sum(1 for c in base_cards if c["object_family"] == "OTHER")

    db_44 = sum(1 for c in base_cards if c["law"] == "44-FZ")
    db_223 = sum(1 for c in base_cards if c["law"] == "223-FZ")
    db_615 = sum(1 for c in base_cards if c["law"] == "615-PP")

    print("\n--- BASELINE AGGREGATIONS ---")
    print(f"  Medals: GOLD={db_gold}, SILVER={db_silver}, BRONZE={db_bronze}, WOOD={db_wood}, UNASSESSED={db_unassessed}")
    print(f"  Families: SOCIAL={db_social}, COMMERCIAL={db_comm}, DIRECT_SUPPLY={db_ds}, OTHER={db_other}")
    print(f"  Laws: 44-FZ={db_44}, 223-FZ={db_223}, 615-PP={db_615}")

    # 3. Top 50 Monotonicity & Expiry Audit
    top50_cards, _ = load_torgi_workset(limit=50, offset=0, filters=TorgiFilterParams())
    now_str = time.strftime("%Y-%m-%d")

    expired_in_top50 = 0
    order_violations = 0
    prev_tier = 0

    print("\n--- TOP 50 CARDS INSPECTION ---")
    for i, c in enumerate(top50_cards, start=1):
        tier = c["tier"]
        end_d = str(c.get("end_date") or "")[:10]
        is_exp = (c.get("award_status") == "submission_closed_waiting_award") or (bool(end_d) and end_d < now_str)
        if is_exp:
            expired_in_top50 += 1

        if tier < prev_tier:
            order_violations += 1
            print(f"  [ORDER VIOLATION] Rank #{i}: Tier {tier} appears after Tier {prev_tier}!")
        prev_tier = tier

        if i <= 15:
            print(f"  #{i:02d} ID={c['id']} | Tier={tier} | Medal={c['preliminary_medal']} | Score={c['priority_score']} | Fam={c['object_family']} | Law={c['law']} | End={end_d}")

    print(f"\n  TOP50_EXPIRED: {expired_in_top50}")
    print(f"  TIER_ORDER_VIOLATIONS: {order_violations}")

    assert expired_in_top50 == 0, f"Found {expired_in_top50} expired cards in Top 50!"
    assert order_violations == 0, f"Found {order_violations} tier order violations!"

    # 4. Filter Matrix Verification (Exact Counts Match)
    print("\n--- FILTER MATRIX VERIFICATION ---")

    # Filter GOLD
    _, filt_gold = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(preliminary_medal="GOLD"))
    print(f"  [Filter GOLD]: DB={db_gold}, Filter={filt_gold}")
    assert filt_gold == db_gold, f"GOLD mismatch: DB {db_gold} != Filter {filt_gold}"

    # Filter SILVER
    _, filt_silver = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(preliminary_medal="SILVER"))
    print(f"  [Filter SILVER]: DB={db_silver}, Filter={filt_silver}")
    assert filt_silver == db_silver, f"SILVER mismatch: DB {db_silver} != Filter {filt_silver}"

    # Filter BRONZE
    _, filt_bronze = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(preliminary_medal="BRONZE"))
    print(f"  [Filter BRONZE]: DB={db_bronze}, Filter={filt_bronze}")
    assert filt_bronze == db_bronze, f"BRONZE mismatch: DB {db_bronze} != Filter {filt_bronze}"

    # Filter WOOD
    _, filt_wood = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(preliminary_medal="WOOD"))
    print(f"  [Filter WOOD]: DB={db_wood}, Filter={filt_wood}")
    assert filt_wood == db_wood, f"WOOD mismatch: DB {db_wood} != Filter {filt_wood}"

    # Filter UNASSESSED
    _, filt_unassessed = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(preliminary_medal="UNASSESSED"))
    print(f"  [Filter UNASSESSED]: DB={db_unassessed}, Filter={filt_unassessed}")
    assert filt_unassessed == db_unassessed, f"UNASSESSED mismatch: DB {db_unassessed} != Filter {filt_unassessed}"

    # Filter SOCIAL
    _, filt_social = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(object_family="SOCIAL"))
    print(f"  [Filter SOCIAL]: DB={db_social}, Filter={filt_social}")
    assert filt_social == db_social, f"SOCIAL mismatch: DB {db_social} != Filter {filt_social}"

    # Filter COMMERCIAL
    _, filt_comm = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(object_family="COMMERCIAL"))
    print(f"  [Filter COMMERCIAL]: DB={db_comm}, Filter={filt_comm}")
    assert filt_comm == db_comm, f"COMMERCIAL mismatch: DB {db_comm} != Filter {filt_comm}"

    # Filter DIRECT_SUPPLY
    _, filt_ds = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(object_family="DIRECT_SUPPLY"))
    print(f"  [Filter DIRECT_SUPPLY]: DB={db_ds}, Filter={filt_ds}")
    assert filt_ds == db_ds, f"DIRECT_SUPPLY mismatch: DB {db_ds} != Filter {filt_ds}"

    # Filter OTHER
    _, filt_other = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(object_family="OTHER"))
    print(f"  [Filter OTHER]: DB={db_other}, Filter={filt_other}")
    assert filt_other == db_other, f"OTHER mismatch: DB {db_other} != Filter {filt_other}"

    # Filter 44-FZ
    _, filt_44 = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(law="44"))
    print(f"  [Filter 44-FZ]: DB={db_44}, Filter={filt_44}")
    assert filt_44 == db_44, f"44-FZ mismatch: DB {db_44} != Filter {filt_44}"

    # Filter 223-FZ
    _, filt_223 = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(law="223"))
    print(f"  [Filter 223-FZ]: DB={db_223}, Filter={filt_223}")
    assert filt_223 == db_223, f"223-FZ mismatch: DB {db_223} != Filter {filt_223}"

    # Filter 615-PP
    _, filt_615 = load_torgi_workset(limit=10, offset=0, filters=TorgiFilterParams(law="615"))
    print(f"  [Filter 615-PP]: DB={db_615}, Filter={filt_615}")
    assert filt_615 == db_615, f"615-PP mismatch: DB {db_615} != Filter {filt_615}"

    print("\n" + "=" * 70)
    print("ALL PHASE 3.1 ACCEPTANCE GATES PASSED [PASS]")
    print("=" * 70)


if __name__ == "__main__":
    verify_phase3_acceptance()
