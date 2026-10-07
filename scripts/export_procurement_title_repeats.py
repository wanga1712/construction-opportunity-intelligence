#!/usr/bin/env python3
"""Read-only export of repeated procurement titles for manual canonical classification.

WIP: EXPORT REPEATED PROCUREMENT TITLES FOR MANUAL CANONICAL CLASSIFICATION.

Guarantees:
  * SELECT-only against the CRM DB. No INSERT/UPDATE/DELETE/ALTER/DDL.
  * No Qwen / LLM / embedding / Levenshtein / fuzzy title merging.
  * Conservative exact normalization only (see ``normalize_procurement_title_v1``).
  * Digits are preserved: "сервер 2u", "220 кв", "110 кв" stay distinct groups.

Usage:
    python scripts/export_procurement_title_repeats.py --output taxonomy_repeat_export.xlsx

The XLSX file and the ZIP fallback are export artifacts and must not be committed.

Size note (project style rule, >450 lines): this is a single self-contained,
read-only export tool. The length is driven by the strict, explicitly specified
worksheet/column contract (9 sheets) plus the many aggregations, and it is kept
as one auditable file (rather than decomposed into a package) so the SELECT-only
no-write guarantee stays reviewable in one place.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import sys
import zipfile
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timezone

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO_ROOT, ".env"))

import psycopg2  # noqa: E402

from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402
from src.services.procurement_title_normalizer import (  # noqa: E402
    normalize_procurement_title_v1,
)

UNCLASSIFIED = "UNCLASSIFIED"
UNCLASSIFIED_RAW = {None, "", "SUBCATEGORY_NOT_ASSIGNED"}


# --------------------------------------------------------------------------- #
# Group ids
# --------------------------------------------------------------------------- #
def _sha1_16(value):
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def title_group_id(normalized_title):
    return _sha1_16(normalized_title)


def category_group_id(category_code, normalized_title):
    return _sha1_16(f"{category_code}|{normalized_title}")


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def distribution(counter):
    """Render a Counter as 'key:count' lines, ordered by count desc then key."""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return "\n".join(f"{k}:{v}" for k, v in items)


def codes_seen(counter):
    return ",".join(sorted(str(k) for k in counter))


def sample_titles(titles, limit=5):
    out = []
    seen = set()
    for t in titles:
        if t is None:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= limit:
            break
    return "\n".join(f"{i}. {t}" for i, t in enumerate(out, 1))


def sample_ids(ids, limit=5):
    out = []
    seen = set()
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        out.append(str(i))
        if len(out) >= limit:
            break
    return ",".join(out)


def _money(value):
    return float(value) if value is not None else 0.0


def _mean(values):
    return round(sum(values) / len(values), 4) if values else ""


def _mm(values):
    """Return (min, max) rounded, or blank when no values."""
    if not values:
        return "", ""
    return round(min(values), 4), round(max(values), 4)


# --------------------------------------------------------------------------- #
# Data loading (SELECT only)
# --------------------------------------------------------------------------- #
def load_base_rows(cur):
    """One row per (procurement_id, category_code) for CURRENT opportunities."""
    cur.execute(
        """
        SELECT DISTINCT ON (o.procurement_id, o.commercial_category_code)
            o.procurement_id,
            o.commercial_category_code      AS category_code,
            o.commercial_subcategory_code   AS subcategory_code,
            o.opportunity_track             AS procurement_mode,
            o.category_confidence,
            o.candidate_initial_medal,
            o.current_effective_medal,
            pr.auction_name                 AS title,
            pr.initial_price                AS amount,
            pr.award_status,
            pr.source_table,
            pr.source_id
        FROM crm_procurement_category_opportunities o
        JOIN crm_procurements pr ON pr.id = o.procurement_id
        WHERE o.status = 'CURRENT'
        ORDER BY o.procurement_id, o.commercial_category_code,
                 o.updated_at DESC NULLS LAST, o.id DESC
        """
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_current_row_count(cur):
    cur.execute(
        "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
    )
    return cur.fetchone()[0]


def load_categories(cur):
    cur.execute(
        """
        SELECT id, category_code, category_name, category_kind, is_active
        FROM crm_product_categories
        ORDER BY category_code
        """
    )
    return {
        r[1]: {"id": r[0], "code": r[1], "name": r[2], "kind": r[3], "active": r[4]}
        for r in cur.fetchall()
    }


def load_subcategories(cur):
    cur.execute(
        """
        SELECT id, category_id, subcategory_code, subcategory_name,
               subcategory_kind, is_active, source
        FROM crm_product_subcategories
        ORDER BY category_id, subcategory_code
        """
    )
    rows = cur.fetchall()
    by_id = {r[0]: r for r in rows}
    valid_codes = {r[2] for r in rows}
    return rows, by_id, valid_codes


def load_terms(cur):
    cur.execute(
        """
        SELECT pc.category_code, ps.subcategory_code, ps.subcategory_name,
               t.term_type, t.phrase, t.weight, t.source
        FROM crm_product_subcategory_terms t
        JOIN crm_product_subcategories ps ON ps.id = t.subcategory_id
        JOIN crm_product_categories pc ON pc.id = ps.category_id
        WHERE t.is_active
        ORDER BY pc.category_code, ps.subcategory_code, t.term_type, t.phrase
        """
    )
    return cur.fetchall()


def load_doc_facts(cur):
    """Map procurement_id -> list of (category_code, subcategory_code).

    Linkage uses crm_object_subcategory_links.(registry_type, tender_id) against
    crm_procurements.(source_table, source_id), which is unique (verified
    read-only during this WIP). Returns None if the join cannot be validated.
    """
    cur.execute(
        "SELECT count(*), count(DISTINCT (source_table, source_id)) FROM crm_procurements"
    )
    total, distinct_pair = cur.fetchone()
    if total != distinct_pair:
        return None
    cur.execute(
        """
        SELECT pr.id, l.category_code, l.subcategory_code
        FROM crm_object_subcategory_links l
        JOIN crm_procurements pr
          ON pr.source_id = l.tender_id AND pr.source_table = l.registry_type
        """
    )
    facts = defaultdict(list)
    for pid, cat, sub in cur.fetchall():
        facts[pid].append((cat, sub))
    return facts


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #
def _empty_group():
    return {
        "proc_ids": OrderedDict(),
        "titles": OrderedDict(),
        "amounts": [],
        "total_amount": 0.0,
        "max_amount": 0.0,
        "subcats": Counter(),
        "modes": Counter(),
        "init_medals": Counter(),
        "curr_medals": Counter(),
        "conf": [],
        "awarded": 0,
        "open": 0,
        "unclassified": 0,
        "classified": 0,
    }


def build_groups(rows, categories, valid_codes):
    category_groups = defaultdict(_empty_group)
    global_groups = defaultdict(_empty_group)

    for r in rows:
        cat = r["category_code"]
        ntitle = normalize_procurement_title_v1(r["title"])
        raw_sub = r["subcategory_code"]
        mode = r["procurement_mode"] or "UNKNOWN"
        init_medal = r["candidate_initial_medal"] or "NONE"
        curr_medal = r["current_effective_medal"] or "NONE"
        conf = float(r["category_confidence"]) if r["category_confidence"] is not None else None
        amount = _money(r["amount"])
        proc_id = r["procurement_id"]

        if raw_sub in UNCLASSIFIED_RAW or raw_sub not in valid_codes:
            sub = UNCLASSIFIED
            is_unclassified = True
        else:
            sub = raw_sub
            is_unclassified = False

        for group in (category_groups[(cat, ntitle)], global_groups[ntitle]):
            group["proc_ids"].setdefault(proc_id, None)
            group["titles"].setdefault(r["title"], None)
            group["amounts"].append(amount)
            group["total_amount"] += amount
            group["max_amount"] = max(group["max_amount"], amount)
            group["subcats"][sub] += 1
            group["modes"][mode] += 1
            group["init_medals"][init_medal] += 1
            group["curr_medals"][curr_medal] += 1
            if conf is not None:
                group["conf"].append(conf)
            if r["award_status"] == "awarded":
                group["awarded"] += 1
            elif r["award_status"] in (
                "submission_open",
                "submission_closed_waiting_award",
                "deadline_unknown",
            ):
                group["open"] += 1
            if is_unclassified:
                group["unclassified"] += 1
            else:
                group["classified"] += 1

    return category_groups, global_groups


def representative_title(group):
    counts = Counter()
    for t in group["titles"]:
        if t:
            counts[t] += 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]


def group_metrics(group):
    repeat = len(group["proc_ids"])
    total = round(group["total_amount"], 2)
    avg = round(group["total_amount"] / repeat, 2) if repeat else 0.0
    return repeat, total, avg, round(group["max_amount"], 2)


def impact_score(repeat, total_amount):
    return round(repeat * math.log(1.0 + max(0.0, total_amount)), 4)


CATEGORY_REPEAT_COLUMNS = [
    "category_group_id", "title_group_id",
    "current_category_code", "current_category_name",
    "normalized_title", "representative_title",
    "repeat_count", "total_amount", "avg_amount", "max_amount",
    "subcategory_codes_seen", "subcategory_distribution",
    "procurement_modes", "mode_distribution",
    "initial_medal_distribution", "current_medal_distribution",
    "category_confidence_min", "category_confidence_avg", "category_confidence_max",
    "open_count", "awarded_count",
    "unclassified_count", "classified_count",
    "sample_procurement_ids", "sample_titles",
    "impact_score",
]


def build_category_repeat_rows(category_groups, categories):
    out = []
    for (cat, ntitle), g in category_groups.items():
        repeat, total, avg, mx = group_metrics(g)
        if repeat < 2:
            continue
        cmin, cmax = _mm(g["conf"])
        out.append({
            "category_group_id": category_group_id(cat, ntitle),
            "title_group_id": title_group_id(ntitle),
            "current_category_code": cat,
            "current_category_name": categories.get(cat, {}).get("name", ""),
            "normalized_title": ntitle,
            "representative_title": representative_title(g),
            "repeat_count": repeat,
            "total_amount": total,
            "avg_amount": avg,
            "max_amount": mx,
            "subcategory_codes_seen": codes_seen(g["subcats"]),
            "subcategory_distribution": distribution(g["subcats"]),
            "procurement_modes": codes_seen(g["modes"]),
            "mode_distribution": distribution(g["modes"]),
            "initial_medal_distribution": distribution(g["init_medals"]),
            "current_medal_distribution": distribution(g["curr_medals"]),
            "category_confidence_min": cmin,
            "category_confidence_avg": _mean(g["conf"]),
            "category_confidence_max": cmax,
            "open_count": g["open"],
            "awarded_count": g["awarded"],
            "unclassified_count": g["unclassified"],
            "classified_count": g["classified"],
            "sample_procurement_ids": sample_ids(g["proc_ids"]),
            "sample_titles": sample_titles(g["titles"]),
            "impact_score": impact_score(repeat, total),
        })
    out.sort(key=lambda r: (-r["repeat_count"], -r["total_amount"]))
    return out


GLOBAL_REPEAT_COLUMNS = [
    "title_group_id", "normalized_title", "representative_title",
    "repeat_count", "total_amount",
    "categories_seen", "category_distribution",
    "subcategories_seen", "subcategory_distribution",
    "mode_distribution",
    "current_medal_distribution",
    "category_confidence_min", "category_confidence_avg", "category_confidence_max",
    "sample_procurement_ids", "sample_titles",
    "impact_score",
]


def build_global_repeat_rows(global_groups):
    out = []
    for ntitle, g in global_groups.items():
        repeat, total, avg, mx = group_metrics(g)
        if repeat < 2:
            continue
        cats = Counter()
        for cat, cg in _iter_category_counts(g):
            cats[cat] += cg
        cmin, cmax = _mm(g["conf"])
        row = {
            "title_group_id": title_group_id(ntitle),
            "normalized_title": ntitle,
            "representative_title": representative_title(g),
            "repeat_count": repeat,
            "total_amount": total,
            "categories_seen": codes_seen(cats),
            "category_distribution": distribution(cats),
            "subcategories_seen": codes_seen(g["subcats"]),
            "subcategory_distribution": distribution(g["subcats"]),
            "mode_distribution": distribution(g["modes"]),
            "current_medal_distribution": distribution(g["curr_medals"]),
            "category_confidence_min": cmin,
            "category_confidence_avg": _mean(g["conf"]),
            "category_confidence_max": cmax,
            "sample_procurement_ids": sample_ids(g["proc_ids"]),
            "sample_titles": sample_titles(g["titles"]),
            "impact_score": impact_score(repeat, total),
        }
        out.append(row)
    out.sort(key=lambda r: (-r["repeat_count"], -r["total_amount"]))
    return out


def _iter_category_counts(global_group):
    """Yield (category_code, count) for one global group from its stored mapping."""
    return global_group.get("_cats", {}).items()


def attach_category_counts(global_groups, category_groups):
    """Populate per-category counts onto global groups (for category_distribution)."""
    for (cat, ntitle), cg in category_groups.items():
        gg = global_groups[ntitle]
        gg.setdefault("_cats", Counter())[cat] += len(cg["proc_ids"])


# --------------------------------------------------------------------------- #
# Subtables
# --------------------------------------------------------------------------- #
def build_taxonomy_rows(categories, subcategories_rows):
    by_cat_id = defaultdict(list)
    for r in subcategories_rows:
        by_cat_id[r[1]].append(r)
    out = []
    for code, c in categories.items():
        subs = by_cat_id.get(c["id"], [])
        if not subs:
            out.append({
                "category_code": code, "category_name": c["name"],
                "category_kind": c["kind"], "category_active": c["active"],
                "subcategory_code": "", "subcategory_name": "",
                "subcategory_kind": "", "subcategory_active": "", "source": "",
            })
        for s in subs:
            out.append({
                "category_code": code, "category_name": c["name"],
                "category_kind": c["kind"], "category_active": c["active"],
                "subcategory_code": s[2], "subcategory_name": s[3],
                "subcategory_kind": s[4], "subcategory_active": s[5],
                "source": s[6],
            })
    return out


TAXONOMY_COLUMNS = [
    "category_code", "category_name", "category_kind", "category_active",
    "subcategory_code", "subcategory_name", "subcategory_kind",
    "subcategory_active", "source",
]
TERM_RULE_COLUMNS = [
    "category_code", "subcategory_code", "subcategory_name",
    "term_type", "phrase", "weight", "source",
]


def build_current_product_taxonomy(categories, subcategories_rows):
    """category_code -> comma-joined active PRODUCT subcategory codes."""
    by_cat_id = defaultdict(list)
    for s in subcategories_rows:
        if s[4] == "PRODUCT" and s[5] is True:
            by_cat_id[s[1]].append(s[2])
    return {
        code: ",".join(sorted(by_cat_id.get(c["id"], [])))
        for code, c in categories.items()
    }


def build_category_stats(rows, category_groups, categories):
    per_cat = defaultdict(lambda: {"procs": set(), "titles": set(), "repeat_procs": set(), "repeat_groups": 0})
    for r in rows:
        cat = r["category_code"]
        ntitle = normalize_procurement_title_v1(r["title"])
        per_cat[cat]["procs"].add(r["procurement_id"])
        per_cat[cat]["titles"].add(ntitle)
    for (cat, ntitle), g in category_groups.items():
        if len(g["proc_ids"]) >= 2:
            per_cat[cat]["repeat_groups"] += 1
            per_cat[cat]["repeat_procs"].update(g["proc_ids"].keys())
    out = []
    for cat, d in sorted(per_cat.items()):
        total = len(d["procs"])
        covered = len(d["repeat_procs"])
        out.append({
            "category_code": cat,
            "category_name": categories.get(cat, {}).get("name", ""),
            "category_kind": categories.get(cat, {}).get("kind", ""),
            "total_procurements": total,
            "distinct_normalized_titles": len(d["titles"]),
            "repeat_groups": d["repeat_groups"],
            "procurements_in_repeat_groups": covered,
            "repeat_coverage_pct": round(100.0 * covered / total, 2) if total else 0.0,
        })
    return out


def build_doc_fact_rows(category_repeat_rows, facts):
    if not facts:
        return None
    out = []
    for r in category_repeat_rows:
        group_procs = r["_proc_ids"]
        touched = set()
        subcat_counter = Counter()
        for pid in group_procs:
            for _fcat, fsub in facts.get(pid, []):
                touched.add(pid)
                subcat_counter[fsub or UNCLASSIFIED] += 1
        out.append({
            "category_group_id": r["category_group_id"],
            "procurements_with_doc_fact": len(touched),
            "doc_fact_subcategories": codes_seen(subcat_counter),
            "doc_fact_distribution": distribution(subcat_counter),
        })
    return out


DOC_FACT_COLUMNS = [
    "category_group_id", "procurements_with_doc_fact",
    "doc_fact_subcategories", "doc_fact_distribution",
]


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
def write_xlsx(path, sheets):
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    for name, columns, rows in sheets:
        ws = wb.create_sheet(title=name)
        ws.append(columns)
        for row in rows:
            ws.append([row.get(c, "") for c in columns])
    wb.save(path)


def write_zip(path, sheets):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, columns, rows in sheets:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(columns)
            for row in rows:
                w.writerow([row.get(c, "") for c in columns])
            zf.writestr(f"{name}.csv", buf.getvalue().encode("utf-8"))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="taxonomy_repeat_export.xlsx")
    ap.add_argument("--top-impact-limit", type=int, default=1000)
    ap.add_argument("--singleton-limit", type=int, default=500)
    args = ap.parse_args(argv)

    conn = psycopg2.connect(**require_crm_db_connect_kwargs())
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()

    raw_current_rows = load_current_row_count(cur)
    categories = load_categories(cur)
    subcategories_rows, sub_by_id, valid_codes = load_subcategories(cur)
    rows = load_base_rows(cur)
    terms = load_terms(cur)
    facts = load_doc_facts(cur)

    category_groups, global_groups = build_groups(rows, categories, valid_codes)
    attach_category_counts(global_groups, category_groups)

    category_repeat_rows = build_category_repeat_rows(category_groups, categories)
    global_repeat_rows = build_global_repeat_rows(global_groups)

    # keep full procurement id sets for DOC_FACT join, stripped from output
    for (cat, ntitle), g in category_groups.items():
        if len(g["proc_ids"]) >= 2:
            gid = category_group_id(cat, ntitle)
            for r in category_repeat_rows:
                if r["category_group_id"] == gid:
                    r["_proc_ids"] = list(g["proc_ids"].keys())
                    break

    current_product_taxonomy = build_current_product_taxonomy(categories, subcategories_rows)
    unclassified_repeat_rows = []
    for r in category_repeat_rows:
        if r["unclassified_count"] > 0:
            row = dict(r)
            row["current_product_taxonomy"] = current_product_taxonomy.get(
                r["current_category_code"], ""
            )
            unclassified_repeat_rows.append(row)

    singleton_rows = []
    for (cat, ntitle), g in category_groups.items():
        if len(g["proc_ids"]) != 1:
            continue
        if g["unclassified"] < 1:
            continue
        pid = next(iter(g["proc_ids"]))
        src = next(r for r in rows if r["procurement_id"] == pid
                   and r["category_code"] == cat)
        singleton_rows.append({
            "procurement_id": pid,
            "category_code": cat,
            "category_name": categories.get(cat, {}).get("name", ""),
            "title": src["title"],
            "normalized_title": ntitle,
            "amount": _money(src["amount"]),
            "procurement_mode": src["procurement_mode"] or "UNKNOWN",
            "category_confidence": float(src["category_confidence"])
                if src["category_confidence"] is not None else "",
            "candidate_initial_medal": src["candidate_initial_medal"] or "NONE",
            "current_effective_medal": src["current_effective_medal"] or "NONE",
        })
    singleton_rows.sort(key=lambda r: -float(r["amount"]))
    singleton_rows = singleton_rows[: args.singleton_limit]

    category_stats = build_category_stats(rows, category_groups, categories)
    doc_fact_rows = build_doc_fact_rows(category_repeat_rows, facts)

    product_cat_groups = [
        r for r in category_repeat_rows
        if categories.get(r["current_category_code"], {}).get("kind") == "PRODUCT"
    ]
    product_cat_groups.sort(key=lambda r: -r["impact_score"])
    top_impact_rows = product_cat_groups[: args.top_impact_limit]

    def strip_private(rows_):
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows_]

    sheets = [
        ("CATEGORY_REPEATS", CATEGORY_REPEAT_COLUMNS, strip_private(category_repeat_rows)),
        ("GLOBAL_REPEATS", GLOBAL_REPEAT_COLUMNS, strip_private(global_repeat_rows)),
        ("UNCLASSIFIED_REPEATS",
         CATEGORY_REPEAT_COLUMNS + ["current_product_taxonomy"],
         strip_private(unclassified_repeat_rows)),
        ("HIGH_VALUE_SINGLETONS",
         ["procurement_id", "category_code", "category_name", "title",
          "normalized_title", "amount", "procurement_mode", "category_confidence",
          "candidate_initial_medal", "current_effective_medal"],
         singleton_rows),
        ("TAXONOMY", TAXONOMY_COLUMNS,
         build_taxonomy_rows(categories, subcategories_rows)),
        ("TERM_RULES", TERM_RULE_COLUMNS,
         [dict(zip(TERM_RULE_COLUMNS, t)) for t in terms]),
        ("CATEGORY_REPEAT_STATS",
         ["category_code", "category_name", "category_kind", "total_procurements",
          "distinct_normalized_titles", "repeat_groups",
          "procurements_in_repeat_groups", "repeat_coverage_pct"],
         category_stats),
        ("TOP_IMPACT", CATEGORY_REPEAT_COLUMNS, strip_private(top_impact_rows)),
    ]
    if doc_fact_rows is not None:
        sheets.insert(6, ("DOC_FACT_COVERAGE", DOC_FACT_COLUMNS, doc_fact_rows))

    out_path = os.path.abspath(args.output)
    if out_path.lower().endswith(".zip"):
        write_zip(out_path, sheets)
    else:
        write_xlsx(out_path, sheets)

    # ---- report ---------------------------------------------------------- #
    distinct_proc = {r["procurement_id"] for r in rows}
    distinct_titles = {normalize_procurement_title_v1(r["title"]) for r in rows}
    covered = set()
    for (cat, ntitle), g in category_groups.items():
        if len(g["proc_ids"]) >= 2:
            covered.update(g["proc_ids"].keys())
    coverage_pct = round(100.0 * len(covered) / len(distinct_proc), 2) if distinct_proc else 0.0

    print("EXPORT_SOURCE_DB=crm")
    print(f"CURRENT_OPPORTUNITY_ROWS={raw_current_rows}")
    print(f"DISTINCT_PROCUREMENTS={len(distinct_proc)}")
    print(f"DISTINCT_NORMALIZED_TITLES={len(distinct_titles)}")
    print(f"CATEGORY_REPEAT_GROUPS={len(category_repeat_rows)}")
    print(f"GLOBAL_REPEAT_GROUPS={len(global_repeat_rows)}")
    print(f"UNCLASSIFIED_REPEAT_GROUPS={len(unclassified_repeat_rows)}")
    print(f"PROCUREMENTS_COVERED_BY_REPEAT_GROUPS={len(covered)}")
    print(f"REPEAT_COVERAGE_PCT={coverage_pct}")
    print("CATEGORY_REPEAT_STATS={")
    for s in category_stats:
        print(
            f"  {s['category_code']}:{{procurements:{s['total_procurements']}, "
            f"distinct_titles:{s['distinct_normalized_titles']}, "
            f"repeat_groups:{s['repeat_groups']}, "
            f"repeat_procurements:{s['procurements_in_repeat_groups']}, "
            f"repeat_coverage_pct:{s['repeat_coverage_pct']}}},"
        )
    print("}")
    print(f"HIGH_VALUE_SINGLETONS={len(singleton_rows)}")
    print(f"TAXONOMY_ROWS={len(build_taxonomy_rows(categories, subcategories_rows))}")
    print(f"TERM_RULE_ROWS={len(terms)}")
    print(f"DOC_FACT_EXPORT={'PASS' if doc_fact_rows is not None else 'NOT_JOINABLE'}")
    print("DB_WRITES=0")
    print("QWEN_CALLS=0")
    print("DRAIN_STATUS=UNCHANGED")
    print(f"OUTPUT_FILE={out_path}")
    print(f"OUTPUT_SIZE={os.path.getsize(out_path)}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
