#!/usr/bin/env python3
"""Inspect the delta for contract 0373200081226000248 in both isolated snapshots."""
import subprocess, json

ISO_DB = "eis_s13_parity"

def psql(db, sql):
    out = subprocess.check_output(["psql", "-d", db, "-At", "-c", sql], text=True).strip()
    return out

tables = [
    "reestr_contract_44_fz",
    "reestr_contract_44_fz_awarded",
    "reestr_contract_44_fz_commission_work",
    "reestr_contract_44_fz_unknown",
    "reestr_contract_44_fz_unclear",
    "reestr_contract_44_fz_completed",
]

contract = "0373200081226000248"

print(f"=== Investigating delta for {contract} ===\n")

# Load OLD and NEW snapshots
import os, json as _json
snap_old = _json.load(open("/tmp/eis_s13_parity_work/snap_old.json"))
snap_new = _json.load(open("/tmp/eis_s13_parity_work/snap_new.json"))

for tbl in snap_old.get("tables", {}).keys():
    old_rows = [r for r in snap_old["tables"].get(tbl, []) if r.get("contract_number") == contract]
    new_rows = [r for r in snap_new["tables"].get(tbl, []) if r.get("contract_number") == contract]
    if old_rows or new_rows:
        print(f"\n--- Table: {tbl} ---")
        print("OLD:", old_rows)
        print("NEW:", new_rows)
        if old_rows and new_rows:
            for i, (o, n) in enumerate(zip(old_rows, new_rows)):
                diffs = {k: (o.get(k), n.get(k)) for k in set(list(o.keys()) + list(n.keys())) if o.get(k) != n.get(k)}
                if diffs:
                    print("DIFFS:", diffs)
