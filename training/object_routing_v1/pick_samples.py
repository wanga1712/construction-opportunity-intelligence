"""Pick 30 REAL procurements for the stage-1 review set (boundary cases first).

Runs with the DB-capable venv (.venv313) on S13.  The review window is
deliberately OUTSIDE the training window (2026-04-01..2026-10-01) so the
samples cannot be memorised: here 2025-09-01..2026-04-01.

Usage:
    ./.venv313/bin/python training/object_routing_v1/pick_samples.py \
        --out /home/sergey/crm-training/data/samples.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/CRM_Streamlit/scripts")

import run_second_pass_worker as W  # noqa: E402
from routing_labels import LABELS, build_example  # noqa: E402

COLS = ["id", "auction_name", "customer", "okpd_code", "okpd_name", "object_type"]
BASE_SQL = """
SELECT id, auction_name, customer, okpd_code, okpd_name, object_type
FROM crm_procurements
WHERE end_date >= %s AND end_date < %s
  AND coalesce(auction_name, '') <> ''
  AND auction_name ILIKE %s
LIMIT %s
"""

#: Boundary cases demanded by the WIP (label is derived, never hardcoded).
BOUNDARY = [
    ("school_construction", "%строительств%школ%", 4),
    ("school_construction", "%школ%строительств%", 3),
    ("hospital_repair", "%ремонт%больниц%", 4),
    ("computers_to_school", "%школ%компьютер%", 4),
    ("computers_to_school", "%компьютер%школ%", 3),
    ("printer_cartridges", "%картридж%", 5),
    ("building_materials_supply", "%поставка%материал%", 5),
    ("design_work", "%проектировани%", 5),
    ("capital_repair", "%капитальный ремонт%", 5),
]

GROUPS = ("SOCIAL", "PROJECT", "DIRECT_SUPPLY")
GROUP_QUOTA = 10


def fetch(crm, date_from, date_to, pattern, limit):
    with crm.cursor() as cur:
        cur.execute(BASE_SQL, (date_from, date_to, pattern, limit))
        return [dict(zip(COLS, row)) for row in cur.fetchall()]


def random_pool(crm, date_from, date_to, limit):
    sql = """
    SELECT id, auction_name, customer, okpd_code, okpd_name, object_type
    FROM crm_procurements
    WHERE end_date >= %s AND end_date < %s
      AND coalesce(auction_name, '') <> ''
    ORDER BY random()
    LIMIT %s
    """
    with crm.cursor() as cur:
        cur.execute(sql, (date_from, date_to, limit))
        return [dict(zip(COLS, row)) for row in cur.fetchall()]


def to_record(row, group, source):
    example = build_example(
        {
            "id": row["id"],
            "title": row["auction_name"],
            "okpd_code": row["okpd_code"],
            "okpd_name": row["okpd_name"],
            "customer": row["customer"],
            "object_type": row["object_type"],
        }
    )
    return {
        "crm_id": row["id"],
        "title": row["auction_name"],
        "customer": row["customer"],
        "okpd_code": row["okpd_code"],
        "okpd_name": row["okpd_name"],
        "group": group,
        "source": source,
        "labels": example["labels"],
        "messages": example["messages"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="date_from", default="2025-09-01")
    ap.add_argument("--to", dest="date_to", default="2026-04-01")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    crm = W.get_crm_connection()
    picked: list = []
    seen = set()

    for name, pattern, limit in BOUNDARY:
        for row in fetch(crm, args.date_from, args.date_to, pattern, limit):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            picked.append(to_record(row, "boundary:" + name, "boundary"))

    fills = {group: 0 for group in GROUPS}
    for record in picked:
        for group in GROUPS:
            if record["labels"][group]:
                fills[group] += 1

    need = {group: max(0, GROUP_QUOTA - fills[group]) for group in GROUPS}
    print("after boundary fills:", fills, "need:", need, flush=True)

    if any(need.values()):
        rng = random.Random(args.seed)
        pool = random_pool(crm, args.date_from, args.date_to, 6000)
        rng.shuffle(pool)
        for row in pool:
            if not any(need[group] > 0 for group in GROUPS):
                break
            if row["id"] in seen:
                continue
            record = to_record({k: row[k] for k in COLS}, "fill", "random_pool")
            used = False
            for group in GROUPS:
                if need[group] > 0 and record["labels"][group]:
                    need[group] -= 1
                    used = True
            if used:
                seen.add(row["id"])
                picked.append(record)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for record in picked:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    totals = {group: sum(1 for r in picked if r["labels"][group]) for group in GROUPS}
    print("wrote %s rows=%d positives=%s" % (args.out, len(picked), totals), flush=True)
    print("boundary=%d fill=%d" % (
        sum(1 for r in picked if r["source"] == "boundary"),
        sum(1 for r in picked if r["source"] == "random_pool"),
    ), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())