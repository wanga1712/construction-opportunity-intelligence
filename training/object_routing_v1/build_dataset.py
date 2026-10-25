"""Build the STAGE 1 object-routing dataset from real CRM procurements.

Ground truth is the project's existing deterministic routing authority
(``routing_labels.derive_labels``), never an old model medal.

Usage (on S13):
    ./.venv313/bin/python training/object_routing_v1/build_dataset.py \
        --out /home/sergey/crm-training/data --from 2026-04-01 --to 2026-10-01
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/CRM_Streamlit/scripts")

import run_second_pass_worker as W  # noqa: E402
from routing_labels import LABELS, PROMPT_VERSION, build_example  # noqa: E402

POOL_SQL = """
SELECT id, auction_name, customer, okpd_code, okpd_name, object_type, crm_category, crm_stage
FROM crm_procurements
WHERE end_date >= %s AND end_date < %s
  AND coalesce(auction_name, '') <> ''
"""

_TITLE_NOISE = re.compile(r"[^0-9a-zа-яё]+")


def norm_title(title: str) -> str:
    return _TITLE_NOISE.sub(" ", str(title or "").lower()).strip()[:150]


def combo(labels: dict) -> str:
    return "|".join("%s=%d" % (n, 1 if labels[n] else 0) for n in LABELS)


def load_pool(crm, date_from: str, date_to: str):
    with crm.cursor() as cur:
        cur.execute(POOL_SQL, (date_from, date_to))
        cols = ["id", "auction_name", "customer", "okpd_code", "okpd_name", "object_type",
                "crm_category", "crm_stage"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--per-bucket", type=int, default=450)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-frac", type=float, default=0.10)
    ap.add_argument("--test-frac", type=float, default=0.10)
    args = ap.parse_args()

    crm = W.get_crm_connection()
    rows = load_pool(crm, args.date_from, args.date_to)
    print("pool rows:", len(rows))

    seen_titles = set()
    buckets = defaultdict(list)
    for row in rows:
        key = norm_title(row["auction_name"])
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
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
        buckets[combo(example["labels"])].append(example)

    rng = random.Random(args.seed)
    selected = []
    for key in sorted(buckets):
        items = buckets[key]
        rng.shuffle(items)
        take = items[: args.per_bucket]
        selected.extend(take)
        print("bucket %-42s available=%-7d taken=%d" % (key, len(items), len(take)))

    rng.shuffle(selected)
    n = len(selected)
    n_val = max(1, int(n * args.val_frac))
    n_test = max(1, int(n * args.test_frac))
    test = selected[:n_test]
    val = selected[n_test : n_test + n_val]
    train = selected[n_test + n_val :]

    os.makedirs(args.out, exist_ok=True)
    for name, split in (("train", train), ("validation", val), ("test", test)):
        path = os.path.join(args.out, "%s.jsonl" % name)
        with open(path, "w", encoding="utf-8") as fh:
            for ex in split:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print("wrote", path, len(split))

    marginals = {}
    for name in LABELS:
        marginals[name] = {
            "train": sum(1 for e in train if e["labels"][name]),
            "validation": sum(1 for e in val if e["labels"][name]),
            "test": sum(1 for e in test if e["labels"][name]),
        }
    stats = {
        "prompt_version": PROMPT_VERSION,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "pool_rows": len(rows),
        "unique_titles": len(seen_titles),
        "per_bucket_cap": args.per_bucket,
        "val_frac": args.val_frac,
        "test_frac": args.test_frac,
        "sizes": {"train": len(train), "validation": len(val), "test": len(test)},
        "positives": marginals,
        "bucket_available": {k: len(v) for k, v in sorted(buckets.items())},
        "combos_train": dict(Counter(combo(e["labels"]) for e in train).most_common()),
    }
    with open(os.path.join(args.out, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: stats[k] for k in ("sizes", "positives")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())