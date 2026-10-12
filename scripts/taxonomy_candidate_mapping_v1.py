"""TAXONOMY_CANDIDATE_MAPPING_V1: draft diff реестра для кандидатов категорий.

Read-only: CRM/queue/UI/HTTP не трогаются. Для каждого кандидата предлагается
действие (existing subcategory / new subcategory / new top category / synonym /
material family / object-system / reject) и считается, что это реально найдёт
в уже накопленном корпусе (distinct procurements + CURRENT opportunities).

Запуск: bash scratch/_run_py.sh scripts/taxonomy_candidate_mapping_v1.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=False)
sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402

from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402

WORK_RE = re.compile(r"(разборк|устройств|монтаж|укладк|обшивк|демонтаж|установк|ремонт|окраск)", re.I)
OBJECT_RE = re.compile(r"(трубопровод|систем|сеть|конструкц|сооружен|покрытие|потолк)", re.I)
FAMILY_RE = re.compile(r"(смес|материал|издели|ресурс|продукц)", re.I)

#: Кураторские предложения для кандидатов, которые уже разобраны глазами.
CURATED = {
    "гипсокартонн гкл": ("NEW_TOP_CATEGORY_REQUIRED", "Листовые материалы (ГКЛ/ГВЛ)", None),
    "гипсокартонн гклв": ("NEW_TOP_CATEGORY_REQUIRED", "Листовые материалы (ГКЛ/ГВЛ)", None),
    "гипсокартонн влагостойк": ("NEW_TOP_CATEGORY_REQUIRED", "Листовые материалы (ГКЛ/ГВЛ)", None),
    "сталь арматурн": ("MAP_TO_EXISTING_SUBCATEGORY", "Арматура", "steel_rebar"),
    "арматурн горячекатан": ("MAP_TO_EXISTING_SUBCATEGORY", "Арматура", "steel_rebar"),
    "пленк полиэтиленов": ("NEW_SUBCATEGORY_REQUIRED", "Полимерные плёнки", "waterproofing"),
    "труб стальн": ("NEW_SUBCATEGORY_REQUIRED", "Стальные трубы", None),
    "пвх профил": ("NEW_SUBCATEGORY_REQUIRED", "ПВХ-профили", None),
    "бетон бст": ("MAP_TO_EXISTING_SUBCATEGORY", "Бетонные смеси", "concrete"),
    "плитк керамогранитн": ("SYNONYM_EXISTING", "существующая подкатегория керамогранита", None),
    "линолеум поливинилхлоридн": ("SYNONYM_EXISTING", "flooring/линолеум", None),
    "трубопровод из": ("OBJECT_SYSTEM", None, None),
    "трубопровод водоснабжени": ("OBJECT_SYSTEM", None, None),
    "внутренних трубопровод": ("OBJECT_SYSTEM", None, None),
}


def connect():
    k = dict(require_crm_db_connect_kwargs())
    di = psycopg2.connect(host=k["host"], port=int(k["port"]), user=k["user"],
                          password=k["password"],
                          dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"))
    crm = psycopg2.connect(**k)
    return di, crm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=28)
    ap.add_argument("--out", default="/tmp/taxonomy_mapping_v1.json")
    args = ap.parse_args()

    di, crm = connect()
    cur = di.cursor()
    cur.execute("""
        SELECT phrase_normalized, distinct_procurements, occurrences, example_quote
          FROM category_phrase_candidates
         WHERE bucket='CATEGORY_CANDIDATE'
         ORDER BY distinct_procurements DESC, occurrences DESC LIMIT %s
    """, (args.top,))
    candidates = [dict(zip(("phrase", "procs", "occ", "quote"), r)) for r in cur.fetchall()]
    cur.execute("""
        SELECT phrase_normalized, distinct_procurements, occurrences, example_quote
          FROM category_phrase_candidates
         WHERE bucket='CATEGORY_CANDIDATE' AND phrase_normalized LIKE 'гипсокартон%'
         ORDER BY distinct_procurements DESC
    """)
    dw = [dict(zip(("phrase", "procs", "occ", "quote"), r)) for r in cur.fetchall()]
    seen = {c["phrase"] for c in candidates}
    for d in dw:
        if d["phrase"] not in seen:
            candidates.append(d)
            seen.add(d["phrase"])
    di.close()

    # существующая таксономия (read-only)
    cc = crm.cursor()
    cc.execute("""SELECT c.category_code, c.category_name, s.subcategory_code, s.subcategory_name
                    FROM crm_product_categories c
                    LEFT JOIN crm_product_subcategories s ON s.category_id = c.id AND s.is_active""")
    taxonomy = cc.fetchall()
    cc.execute("SELECT lower(phrase) FROM crm_product_subcategory_terms WHERE is_active")
    terms = {r[0] for r in cc.fetchall()}
    crm.close()

    # --- оценка прироста: что кандидат реально найдёт в накопленном корпусе ---
    tokens = sorted({c["phrase"].split()[0] for c in candidates})
    patterns = ["%" + t[:8] + "%" for t in tokens]
    di2, _ = connect()
    cur2 = di2.cursor(name="taxmap")
    cur2.itersize = 20000
    cur2.execute("""
        SELECT m.procurement_id, d.row_data::text
          FROM document_match_details d
          JOIN document_matches m ON m.id = d.match_id
         WHERE d.row_data IS NOT NULL AND d.row_data::text <> '{}'
           AND d.row_data::text ILIKE ANY(%s)
    """, (patterns,))
    hits = defaultdict(set)
    for pid, row in cur2:
        low = row.lower()
        for tok, pat in zip(tokens, patterns):
            if pat.strip("%") in low:
                hits[tok].add(pid)
    di2.close()

    all_pids = sorted({p for s in hits.values() for p in s})
    opp_by_pid = defaultdict(int)
    if all_pids:
        crm2 = psycopg2.connect(**require_crm_db_connect_kwargs())
        cc2 = crm2.cursor()
        cc2.execute("""SELECT procurement_id, count(*) FROM crm_procurement_category_opportunities
                        WHERE status='CURRENT' AND procurement_id = ANY(%s) GROUP BY 1""", (all_pids,))
        for pid, n in cc2.fetchall():
            opp_by_pid[int(pid)] = int(n)
        crm2.close()

    counts = defaultdict(int)
    new_terms, collisions, ambiguous = [], [], []
    rows = []
    for c in candidates:
        phrase = c["phrase"]
        head = phrase.split()[0]
        if phrase in CURATED:
            action, target, parent = CURATED[phrase]
        elif WORK_RE.search(phrase):
            action, target, parent = "REJECTED", "работа, не товар", None
        elif OBJECT_RE.search(phrase):
            action, target, parent = "OBJECT_SYSTEM", None, None
        elif FAMILY_RE.search(phrase):
            action, target, parent = "MATERIAL_FAMILY", None, None
        elif any(phrase in t or t in phrase for t in terms if len(t) > 6):
            action, target, parent = "SYNONYM_EXISTING", "уже есть в terms", None
        else:
            action, target, parent = "AMBIGUOUS", None, None
        counts[action] += 1
        if action in ("NEW_SUBCATEGORY_REQUIRED", "NEW_TOP_CATEGORY_REQUIRED", "SYNONYM_EXISTING"):
            new_terms.append(phrase)
        if action == "AMBIGUOUS":
            ambiguous.append(phrase)
        gain_pids = hits.get(head, set())
        rows.append({
            "candidate": phrase, "action": action, "target": target, "parent_category": parent,
            "occurrences": c["occ"], "procurements_with_phrase": len(gain_pids) or c["procs"],
            "estimated_current_opportunities": sum(opp_by_pid.get(p, 0) for p in gain_pids),
            "example_quote": c["quote"],
        })

    print("CANDIDATES_REVIEWED=%d" % len(candidates))
    for key in ("MAP_TO_EXISTING_SUBCATEGORY", "NEW_SUBCATEGORY_REQUIRED",
                "NEW_TOP_CATEGORY_REQUIRED", "SYNONYM_EXISTING", "MATERIAL_FAMILY",
                "OBJECT_SYSTEM", "REJECTED", "AMBIGUOUS"):
        if counts.get(key):
            print("%s=%d" % (key, counts[key]))
    print("NEW_SEARCH_TERMS=%d" % len(new_terms))
    print("TERM_COLLISIONS=%d" % len(collisions))
    print("AMBIGUOUS_MAPPINGS=%d" % len(ambiguous))
    print("ESTIMATED_PROCUREMENTS_GAIN=%d" % sum(r["procurements_with_phrase"] for r in rows
                                                 if r["action"].startswith(("NEW_", "MAP_"))))
    print("ESTIMATED_CURRENT_OPPORTUNITIES_GAIN=%d" % sum(r["estimated_current_opportunities"] for r in rows
                                                          if r["action"].startswith(("NEW_", "MAP_"))))
    print("CRM_WRITES=0")
    print("QUEUE_WRITES=0")
    print("HTTP_REQUESTS=0")
    print("UI_CHANGES=0")
    print()
    print("DRAFT_DIFF")
    for r in rows:
        print("   %-26s %-48s %-22s procs=%-4s opps=%s" %
              (r["action"][:26], r["candidate"][:48], str(r["target"])[:22],
               r["procurements_with_phrase"], r["estimated_current_opportunities"]))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"counts": dict(counts), "rows": rows, "new_search_terms": new_terms,
                   "ambiguous": ambiguous, "crm_writes": 0, "queue_writes": 0,
                   "http_requests": 0, "ui_changes": 0}, fh, ensure_ascii=False, indent=2)
    print("REPORT_WRITTEN", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
