#!/usr/bin/env python3
"""Upgrade approved exact-title rules for TAXONOMY GAPS V1.

WIP: TAXONOMY GAPS V1 + RULE UPGRADE. No new AI classification.

Turns already-imported knowledge rules into real rules after the new PRODUCT
subcategories exist:
    * KEEP           -> ASSIGN_SUBCATEGORY (execution_enabled = TRUE)   [same category]
    * cable rules    -> MOVE_CATEGORY  cable_products / ... (exec = FALSE)
    * waterproofing  -> MOVE_CATEGORY target_subcategory = culvert_pipes (exec = FALSE)

Parent-category DML is NOT executed here; MOVE rules stay disabled.

Usage:
    python scripts/upgrade_title_rules_for_taxonomy_gap_v1.py --dry-run
    python scripts/upgrade_title_rules_for_taxonomy_gap_v1.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO_ROOT, ".env"))

from src.infrastructure.crm_connection import connect_crm  # noqa: E402
from src.services.procurement_title_normalizer import (  # noqa: E402
    NORMALIZATION_VERSION,
)

CULVERT_TITLE = (
    "выполнение работ по содержанию автомобильных дорог укладка водопропускной "
    "трубы по ул чкалова в с северное северного муниципального округа "
    "новосибирской области"
)

# (current_category_code, normalized_title) -> target_subcategory_code   [KEEP->ASSIGN]
GAP_ASSIGN = {
    ("computers", "интерактивная панель"): "interactive_panels",
    ("computers", "поставка картриджей"): "printing_consumables",
    ("computers", "поставка расходных материалов для оргтехники"): "printing_consumables",
    ("computers", "поставка картриджей для электрографических печатающих устройств"): "printing_consumables",
    ("computers", "поставка проектора"): "projectors",
    ("computers", "проектор"): "projectors",
    ("computers", "поставка расходных материалов для компьютерной техники"): "computer_consumables",
    ("computers", "поставка комплектующих и запасных частей для многофункциональных устройств"): "printing_parts",
    ("computers", "информационный терминал"): "information_terminals",
    ("lighting", "поставка светильников"): "generic_luminaires",
    ("lighting", "поставка светильников светодиодных"): "generic_luminaires",
    ("lighting", "поставка светодиодных светильников"): "generic_luminaires",
    ("lighting", "поставка ламп светодиодных"): "led_lamps",
    ("lighting", "лампа светодиодная"): "led_lamps",
    ("drainage_water_management", CULVERT_TITLE): "culvert_pipes",
}

# (current_category_code, normalized_title) -> (target_category, target_subcategory)  [MOVE, exec=FALSE]
MOVE_TARGETS = {
    ("cable_support_systems", "поставка кабеля"): ("cable_products", "generic_cables"),
    ("cable_support_systems", "поставка кабельной продукции"): ("cable_products", "generic_cables"),
    ("cable_support_systems", "поставка кабеля силового"): ("cable_products", "power_cables"),
    ("waterproofing", CULVERT_TITLE): ("drainage_water_management", "culvert_pipes"),
}


def load_taxonomy(cur):
    cur.execute("SELECT category_code, category_kind, is_active FROM crm_product_categories")
    cats = {r[0]: {"kind": r[1], "active": r[2]} for r in cur.fetchall()}
    cur.execute(
        """
        SELECT c.category_code, s.subcategory_code, s.subcategory_kind, s.is_active
        FROM crm_product_subcategories s
        JOIN crm_product_categories c ON c.id = s.category_id
        """
    )
    subs = {(r[0], r[1]): {"kind": r[2], "active": r[3]} for r in cur.fetchall()}
    return cats, subs


def load_rules(cur, version):
    cur.execute(
        "SELECT id, current_category_code, normalized_title, action, confidence "
        "FROM crm_procurement_title_rules "
        "WHERE is_active = TRUE AND normalization_version = %s",
        (version,),
    )
    return {(r[1], r[2]): {"id": r[0], "action": r[3], "confidence": r[4]}
            for r in cur.fetchall()}


def _valid_target(cat, sub, cats, subs):
    cinfo = cats.get(cat)
    if not cinfo or not cinfo["active"] or cinfo["kind"] != "PRODUCT":
        return False
    sinfo = subs.get((cat, sub))
    return bool(sinfo and sinfo["active"] and sinfo["kind"] == "PRODUCT")


UPDATE_ASSIGN = """
UPDATE crm_procurement_title_rules
   SET action = 'ASSIGN_SUBCATEGORY',
       target_category_code = %s,
       target_subcategory_code = %s,
       execution_enabled = TRUE,
       updated_at = NOW()
 WHERE id = %s
"""

UPDATE_MOVE = """
UPDATE crm_procurement_title_rules
   SET action = 'MOVE_CATEGORY',
       target_category_code = %s,
       target_subcategory_code = %s,
       execution_enabled = FALSE,
       updated_at = NOW()
 WHERE id = %s
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--normalization-version", default=NORMALIZATION_VERSION)
    args = ap.parse_args(argv)
    if args.apply == args.dry_run:
        print("choose exactly one of --dry-run / --apply")
        return 2

    conn = connect_crm()
    cur = conn.cursor()
    cats, subs = load_taxonomy(cur)
    rules = load_rules(cur, args.normalization_version)

    keep_to_assign, missing, invalid, planned = 0, [], [], []
    for (cat, title), sub in GAP_ASSIGN.items():
        rule = rules.get((cat, title))
        if not rule:
            missing.append(f"ASSIGN {cat}/{title}")
            continue
        if not _valid_target(cat, sub, cats, subs):
            invalid.append(f"ASSIGN {cat}/{sub}")
            continue
        if rule["action"] == "KEEP":
            keep_to_assign += 1
        planned.append(("ASSIGN", rule["id"], cat, sub))

    move_updated, move_planned = 0, []
    for (cat, title), (tcat, tsub) in MOVE_TARGETS.items():
        rule = rules.get((cat, title))
        if not rule:
            missing.append(f"MOVE {cat}/{title}")
            continue
        if not _valid_target(tcat, tsub, cats, subs):
            invalid.append(f"MOVE {tcat}/{tsub}")
            continue
        move_updated += 1
        move_planned.append(("MOVE", rule["id"], tcat, tsub))

    print(f"RULES_FOUND={len(planned) + len(move_planned)}")
    print(f"KEEP_TO_ASSIGN={keep_to_assign}")
    print(f"MOVE_TARGETS_UPDATED={move_updated}")
    print(f"MISSING_RULES={len(missing)}")
    for m in missing:
        print(f"  MISSING {m}")
    print(f"INVALID_TARGETS={len(invalid)}")
    for i in invalid:
        print(f"  INVALID {i}")

    if args.apply:
        written = 0
        for kind, rid, tcat, tsub in planned:
            cur.execute(UPDATE_ASSIGN, (tcat, tsub, rid))
            written += cur.rowcount
        for kind, rid, tcat, tsub in move_planned:
            cur.execute(UPDATE_MOVE, (tcat, tsub, rid))
            written += cur.rowcount
        conn.commit()
        print(f"DB_WRITES={written}")
    else:
        conn.rollback()
        print("DB_WRITES=0")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
