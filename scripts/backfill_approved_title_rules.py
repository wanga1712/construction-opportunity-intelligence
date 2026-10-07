#!/usr/bin/env python3
"""Apply approved exact-title ASSIGN rules to CURRENT opportunities.

WIP: APPROVED EXACT TITLE RULES V1. Read-only scan by default.

Only ``action = ASSIGN_SUBCATEGORY`` with ``execution_enabled = TRUE`` is ever
written, and only onto rows whose ``commercial_subcategory_code`` is currently
unclassified (NULL / '' / 'SUBCATEGORY_NOT_ASSIGNED'). Existing non-null
assignments, medals, categories, and opportunity rows are never touched.
KEEP / MOVE_CATEGORY / REMOVE_CATEGORY are counted but not executed.

Usage:
    python scripts/backfill_approved_title_rules.py --dry-run
    python scripts/backfill_approved_title_rules.py --canary --canary-limit 25
    python scripts/backfill_approved_title_rules.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO_ROOT, ".env"))

from src.infrastructure.crm_connection import connect_crm  # noqa: E402
from src.services.procurement_title_normalizer import (  # noqa: E402
    normalize_procurement_title_v1,
)
from src.services.procurement_title_rule_service import (  # noqa: E402
    ACTION_ASSIGN_SUBCATEGORY,
    SOURCE_APPROVED_TITLE_RULE,
    load_exact_title_rules,
    rule_key,
)

UNCLASSIFIED_SENTINEL = "SUBCATEGORY_NOT_ASSIGNED"


def is_unclassified(code):
    if code is None:
        return True
    return str(code).strip() in ("", UNCLASSIFIED_SENTINEL)


def scan(cur, rules):
    cur.execute(
        """
        SELECT o.id, o.procurement_id, o.commercial_category_code,
               o.commercial_subcategory_code, o.opportunity_track,
               o.routing_version, p.auction_name
        FROM crm_procurement_category_opportunities o
        JOIN crm_procurements p ON p.id = o.procurement_id
        WHERE o.status = 'CURRENT'
        """
    )
    col = [d[0] for d in cur.description]
    rows = [dict(zip(col, raw)) for raw in cur.fetchall()]

    # The unique key is (procurement_id, category, subcategory_code, track,
    # routing_version). One procurement can hold several CURRENT rows for the
    # same category when a sibling row already carries a concrete subcategory.
    # Assigning that same code to another sibling would violate the unique key,
    # so a row is only "ready" when no sibling already has the target code.
    groups = defaultdict(set)
    for r in rows:
        code = r["commercial_subcategory_code"]
        if code is not None and str(code).strip() not in ("", UNCLASSIFIED_SENTINEL):
            groups[(r["procurement_id"], r["commercial_category_code"],
                    r["opportunity_track"], r["routing_version"])].add(str(code).strip())

    scanned = 0
    matched = 0
    by_action = Counter()
    ready = []                 # (opp_id, target_sub, conf, rule_id)
    per_rule = defaultdict(lambda: {"matched": 0, "ready": 0, "already": 0, "conflict": 0})
    assign_ready = assign_already = assign_conflict = 0
    claimed = set()  # (proc_id, cat, track, version, target) written once per batch
    for r in rows:
        scanned += 1
        normalized = normalize_procurement_title_v1(r["auction_name"])
        key = rule_key(normalized, r["commercial_category_code"])
        rule = rules.get(key)
        if not rule:
            continue
        matched += 1
        by_action[rule["action"]] += 1
        if rule["action"] != ACTION_ASSIGN_SUBCATEGORY:
            continue
        bucket = per_rule[normalized]
        bucket["matched"] += 1
        target = str(rule["target_subcategory_code"]).strip()
        siblings = groups.get((r["procurement_id"], r["commercial_category_code"],
                               r["opportunity_track"], r["routing_version"]), set())
        if is_unclassified(r["commercial_subcategory_code"]):
            claim = (r["procurement_id"], r["commercial_category_code"],
                     r["opportunity_track"], r["routing_version"], target)
            if target in siblings or claim in claimed:
                # sibling row already carries this code -> nothing to write
                assign_already += 1
                bucket["already"] += 1
            else:
                claimed.add(claim)
                assign_ready += 1
                bucket["ready"] += 1
                ready.append((r["id"], target, float(rule["confidence"]), rule["id"]))
        elif str(r["commercial_subcategory_code"]).strip() == str(target).strip():
            assign_already += 1
            bucket["already"] += 1
        else:
            assign_conflict += 1
            bucket["conflict"] += 1
    stats = {
        "CURRENT_SCANNED": scanned,
        "TITLE_RULE_MATCHED": matched,
        "ASSIGN_MATCHED": by_action.get(ACTION_ASSIGN_SUBCATEGORY, 0),
        "KEEP_MATCHED": by_action.get("KEEP", 0),
        "MOVE_MATCHED": by_action.get("MOVE_CATEGORY", 0),
        "REMOVE_MATCHED": by_action.get("REMOVE_CATEGORY", 0),
        "ASSIGN_UNCLASSIFIED_READY": assign_ready,
        "ASSIGN_ALREADY_CLASSIFIED": assign_already,
        "ASSIGN_CONFLICTING_CLASSIFIED": assign_conflict,
        "NO_RULE": scanned - matched,
    }
    return stats, ready, per_rule


SNAPSHOT_SQL = """
SELECT id, commercial_category_code, commercial_subcategory_code,
       candidate_initial_medal, current_effective_medal
FROM crm_procurement_category_opportunities WHERE id = ANY(%s)
"""


def snapshot(cur, ids):
    cur.execute(SNAPSHOT_SQL, (ids,))
    return {r[0]: r for r in cur.fetchall()}


def apply_batch(conn, cur, batch):
    """Apply guarded updates; returns (applied, acceptance counters)."""
    ids = [b[0] for b in batch]
    before = snapshot(cur, ids)
    total_before = count_opportunities(cur)
    applied = 0
    for opp_id, target, conf, _rule_id in batch:
        cur.execute(
            """
            UPDATE crm_procurement_category_opportunities o
               SET commercial_subcategory_code = %s,
                   commercial_subcategory_source = %s,
                   commercial_subcategory_confidence = %s,
                   updated_at = NOW()
             WHERE o.id = %s AND o.status = 'CURRENT'
               AND (o.commercial_subcategory_code IS NULL
                    OR btrim(o.commercial_subcategory_code) = ''
                    OR o.commercial_subcategory_code = %s)
               AND NOT EXISTS (
                   SELECT 1 FROM crm_procurement_category_opportunities s
                   WHERE s.procurement_id = o.procurement_id
                     AND s.commercial_category_code = o.commercial_category_code
                     AND s.opportunity_track IS NOT DISTINCT FROM o.opportunity_track
                     AND s.routing_version IS NOT DISTINCT FROM o.routing_version
                     AND s.commercial_subcategory_code = %s
               )
            """,
            (target, SOURCE_APPROVED_TITLE_RULE, conf, opp_id,
             UNCLASSIFIED_SENTINEL, target),
        )
        applied += cur.rowcount
    conn.commit()
    after = snapshot(cur, ids)
    total_after = count_opportunities(cur)

    targets = {b[0]: b[1] for b in batch}
    wrong = overwritten = medals = category = 0
    for opp_id, a in after.items():
        b = before.get(opp_id)
        if b is None:
            continue
        if a[2] != targets.get(opp_id):
            wrong += 1
        if b[2] is not None and str(b[2]).strip() not in ("", UNCLASSIFIED_SENTINEL) \
                and b[2] != a[2]:
            overwritten += 1
        if b[3] != a[3] or b[4] != a[4]:
            medals += 1
        if b[1] != a[1]:
            category += 1
    acceptance = {
        "WRONG_ASSIGNMENTS": wrong,
        "NON_NULL_OVERWRITTEN": overwritten,
        "MEDALS_CHANGED": medals,
        "CATEGORY_CHANGED": category,
        "OPPORTUNITY_CREATED": total_after - total_before,
    }
    return applied, acceptance


def count_opportunities(cur):
    cur.execute("SELECT count(*) FROM crm_procurement_category_opportunities")
    return cur.fetchone()[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--canary", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--canary-limit", type=int, default=25)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    if sum([args.dry_run, args.canary, args.apply]) > 1:
        print("choose at most one of --dry-run / --canary / --apply")
        return 2

    conn = connect_crm()
    cur = conn.cursor()
    rules = load_exact_title_rules(cur)
    stats, ready, per_rule = scan(cur, rules)

    for k in ("CURRENT_SCANNED", "TITLE_RULE_MATCHED", "ASSIGN_MATCHED",
              "KEEP_MATCHED", "MOVE_MATCHED", "REMOVE_MATCHED",
              "ASSIGN_UNCLASSIFIED_READY", "ASSIGN_ALREADY_CLASSIFIED",
              "ASSIGN_CONFLICTING_CLASSIFIED", "NO_RULE"):
        print(f"{k}={stats[k]}")

    print("\n# ASSIGN rules detail")
    for norm, b in sorted(per_rule.items()):
        print(f"  {norm}: matched={b['matched']} unclassified_ready={b['ready']} "
              f"already_classified={b['already']} conflicts={b['conflict']}")

    if args.canary or args.apply:
        batch = ready[: args.canary_limit] if args.canary else ready
        if args.limit:
            batch = batch[: args.limit]
        applied, acceptance = apply_batch(conn, cur, batch)
        print(f"\nCANARY_SELECTED={len(batch)}" if args.canary else f"\nMASS_BATCH={len(batch)}")
        print(f"CANARY_APPLIED={applied}" if args.canary else f"MASS_ASSIGN_APPLIED={applied}")
        for k, v in acceptance.items():
            print(f"{k}={v}")
        print(f"REMAINING_MATCHED_UNCLASSIFIED={len(ready) - applied}")
    else:
        conn.rollback()

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
