"""CATEGORY_DISCOVERY_DYNAMIC_V1: material families -> new embedded categories.

Three mandatory phases (WIP .codex_worktrees/category_discovery_dynamic_v1/WIP.md):

  A) cluster CATEGORY_CANDIDATE phrases into material families
     (headword/stem + OKPD cluster);
  B) fuzzy synonym match of a family against the 16 existing categories
     (category_name / aliases / positive_signals + subcategory search_phrases);
     a hit means SYNONYM_EXISTING and no category is created;
  C) promote the remainder: genuinely new families only, DRAFT / WOOD,
     updated_by='AUTO_CANDIDATE', idempotent by (family, okpd_cluster).

Default mode is a read-only dry run (A+B, no writes). Phase C runs only with
--promote. HTTP is never used; CRM writes happen only under --promote.

Run on S13:
    bash scratch/_run_py.sh scripts/promote_discovered_categories.py
    bash scratch/_run_py.sh scripts/promote_discovered_categories.py --promote
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=False)
sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402

from src.services.commercial_routing_v3.text_normalization import canonical_tokens  # noqa: E402
from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402

try:  # reuse the miner vocabulary instead of duplicating it
    from scripts.mine_category_phrases_v2 import MATERIAL_ROOTS as HEAD_ROOTS
except Exception:  # pragma: no cover - fallback keeps the job runnable
    HEAD_ROOTS = (
        "арматур", "бетон", "асфальт", "труб", "линолеум", "керамогранит",
        "профил", "пленк", "смес", "плит", "лоток", "кабел", "светильник",
        "бордюр", "утеплит", "изоляц", "мембран", "мастик", "герметик",
    )

#: Canonical family name for a headword root: merges inflections and OKPD splits.
HEADWORD_CANONICAL = {
    "арматур": "арматура",
    "керамогранит": "керамогранит",
    "плитк": "плитка",
    "кирпич": "кирпич",
    "стеклопакет": "стеклопакет",
    "двер": "двери",
    "краск": "краска",
    "изоляц": "изоляция",
    "клапан": "запорная_арматура",
    "вентил": "запорная_арматура",
    "раствор": "раствор",
    "смес": "смеси",
    "выравнива": "выравнивающая",
    "труб": "трубы",
    "кабел": "кабель",
    "хомут": "хомут",
    "опор": "опора",
    "профил": "профиль",
    "стекловолокн": "стекловолокно",
}

#: Hard synonym: canonical family -> existing category (wins over fuzzy).
HARD_SYNONYMS = {
    "арматура": "structural_reinforcement",
    "керамогранит": "flooring",
    "плитка": "flooring",
    "раствор": "concrete_materials",
    "смеси": "concrete_materials",
    "выравнивающая": "flooring",
    "трубы": "external_utility_networks",
    "кабель": "cable_products",
    "хомут": "cable_support_systems",
    "опора": "composite_structures",
}

#: Ambiguous one-token heads that must never be fuzzy-matched (manual review).
FUZZY_BLOCKLIST = {"блок"}

DEFAULTS = {
    "min_distinct_procurements": 10,
    "min_occurrences": 20,
    "min_supply_value_rub": 0,
    "okpd_cluster_digits": 4,
    "default_medal": "WOOD",
    "enabled": True,
}

def connect_crm():
    return psycopg2.connect(**require_crm_db_connect_kwargs())


def connect_di():
    kw = dict(require_crm_db_connect_kwargs())
    return psycopg2.connect(
        host=kw["host"],
        port=int(kw["port"]),
        user=kw["user"],
        password=kw["password"],
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    )


def load_config(conn, scope: str = "DEFAULT") -> dict:
    cfg = dict(DEFAULTS)
    cfg["_source"] = "defaults"
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.category_discovery_config')")
        if cur.fetchone()[0] is None:
            return cfg
        cur.execute(
            "select min_distinct_procurements, min_occurrences, min_supply_value_rub,"
            " okpd_cluster_digits, default_medal, enabled"
            " from category_discovery_config where scope_key=%s",
            (scope,),
        )
        row = cur.fetchone()
    if not row:
        return cfg
    keys = list(DEFAULTS)
    cfg.update({k: row[i] for i, k in enumerate(keys)})
    cfg["_source"] = f"table:{scope}"
    return cfg


def load_candidates(conn, min_proc: int, min_occ: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, phrase_normalized, occurrences, distinct_procurements,
                   provenance
            from category_phrase_candidates
            where bucket = 'CATEGORY_CANDIDATE'
              and distinct_procurements >= %s
              and occurrences >= %s
            order by distinct_procurements desc, occurrences desc
            """,
            (min_proc, min_occ),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_okpd_map(conn, procurement_ids: list[int], digits: int) -> dict[int, str]:
    if not procurement_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "select id, left(coalesce(okpd_code, ''), %s) from crm_procurements"
            " where id = any(%s)",
            (digits, procurement_ids),
        )
        return {int(r[0]): (r[1] or "") for r in cur.fetchall()}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return [value] if value else []
        return [str(v) for v in parsed if v] if isinstance(parsed, list) else []
    return []


def load_category_index(conn) -> dict[str, dict]:
    index: dict[str, dict] = defaultdict(lambda: {"name": "", "terms": set()})
    with conn.cursor() as cur:
        cur.execute(
            "select category_code, category_name, aliases, positive_signals"
            " from crm_product_categories"
        )
        for code, name, aliases, signals in cur.fetchall():
            entry = index[code]
            entry["name"] = name or code
            for term in [name] + _as_list(aliases) + _as_list(signals):
                if term:
                    entry["terms"].add(str(term).strip().lower())
        cur.execute(
            """
            select c.category_code, s.search_phrases
            from crm_product_subcategories s
            join crm_product_categories c on c.id = s.category_id
            """
        )
        for code, phrases in cur.fetchall():
            for term in _as_list(phrases):
                if term:
                    index[code]["terms"].add(str(term).strip().lower())
    return index


def pick_headword(tokens: list[str]) -> str:
    best_canonical = ""
    best_len = 0
    for token in tokens:
        for root, canonical in HEADWORD_CANONICAL.items():
            if len(root) >= 3 and token.startswith(root) and len(root) > best_len:
                best_canonical, best_len = canonical, len(root)
    if best_canonical:
        return best_canonical
    # legacy fallback: longest miner-root token
    best: tuple[int, str] | None = None
    for token in tokens:
        for root in HEAD_ROOTS:
            if len(root) >= 4 and token.startswith(root):
                if best is None or len(root) > best[0]:
                    best = (len(root), token)
    if best:
        return best[1]
    return max(tokens, key=len) if tokens else ""


def phase_a(rows: list[dict], okpd_map: dict[int, str]) -> list[dict]:
    families: dict[str, dict] = {}
    for row in rows:
        phrase = str(row["phrase_normalized"] or "").strip()
        tokens = canonical_tokens(phrase)
        if not tokens:
            continue
        prov = row.get("provenance") or {}
        if isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except Exception:
                prov = {}
        pid = prov.get("procurement_id")
        okpd = okpd_map.get(int(pid), "") if pid else ""
        head = pick_headword(tokens)
        fam = families.setdefault(
            head,
            {
                "headword": head,
                "okpd_clusters": set(),
                "okpd_cluster": "",
                "phrases": [],
                "tokens": set(),
                "occurrences": 0,
                "max_procurements": 0,
                "quote": "",
            },
        )
        if okpd:
            fam["okpd_clusters"].add(okpd)
        fam["phrases"].append(phrase)
        fam["tokens"].update(tokens)
        fam["occurrences"] += int(row["occurrences"] or 0)
        fam["max_procurements"] = max(
            fam["max_procurements"], int(row["distinct_procurements"] or 0)
        )
        if not fam["quote"] and row.get("provenance"):
            fam["quote"] = str(prov.get("context") or prov.get("example_quote") or "")
    for fam in families.values():
        clusters = sorted(fam["okpd_clusters"])
        fam["okpd_clusters"] = clusters
        fam["okpd_cluster"] = clusters[0] if len(clusters) == 1 else (
            ",".join(clusters) if clusters else ""
        )
    return sorted(
        families.values(),
        key=lambda f: (f["max_procurements"], f["occurrences"]),
        reverse=True,
    )


def _stem_set(text: str) -> set[str]:
    return set(canonical_tokens(text))


def _token_match(a: str, b: str) -> bool:
    """Russian stems: equality or shared prefix (труб ~ трубопровод)."""
    if a == b:
        return True
    return len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a))


def _term_score(term_tokens: set[str], fam_tokens: set[str]) -> float:
    """Share of the existing-category term covered by the family vocabulary."""
    covered = sum(1 for t in term_tokens if any(_token_match(t, f) for f in fam_tokens))
    return covered / len(term_tokens)


def phase_b(families: list[dict], index: dict[str, dict]) -> None:
    prepared = []
    for code, entry in index.items():
        for term in entry["terms"]:
            tokens = _stem_set(term)
            if not tokens:
                continue
            # a one-token term must be distinctive to count as a synonym
            if len(tokens) == 1 and len(next(iter(tokens))) < 5:
                continue
            prepared.append((code, entry["name"], term, tokens))

    for fam in families:
        hard_code = HARD_SYNONYMS.get(fam["headword"])
        if hard_code:
            fam["synonym_state"] = "SYNONYM_EXISTING"
            fam["matched_category"] = hard_code
            fam["matched_term"] = "hard:" + fam["headword"]
            fam["match_score"] = 1.0
            continue
        if fam["headword"] in FUZZY_BLOCKLIST:
            fam["synonym_state"] = "NEW"
            continue
        fam_tokens = set(fam["tokens"])
        best = None
        for code, name, term, term_tokens in prepared:
            score = _term_score(term_tokens, fam_tokens)
            if score < 1.0:
                continue
            rank = (len(term_tokens), len(term))
            if best is None or rank > best[0]:
                best = (rank, code, name, term)
        if best:
            fam["synonym_state"] = "SYNONYM_EXISTING"
            fam["matched_category"] = best[1]
            fam["matched_term"] = best[3]
            fam["match_score"] = 1.0
        else:
            fam["synonym_state"] = "NEW"


def phase_c(crm, families: list[dict], cfg: dict, apply: bool) -> list[dict]:
    created = []
    new_families = [f for f in families if f.get("synonym_state") == "NEW"]
    if not apply:
        return [{"family": f["headword"], "okpd": f["okpd_cluster"],
                 "action": "DRY_RUN"} for f in new_families]
    from src.services.category_registry_service import create_category

    for fam in new_families:
        code = f"auto_{fam['headword']}_{fam['okpd_cluster'] or 'na'}".lower()
        code = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in code)[:60]
        with crm.cursor() as cur:
            cur.execute("select 1 from crm_product_categories where category_code=%s", (code,))
            if cur.fetchone():
                created.append({"family": fam["headword"], "category_code": code,
                                "action": "EXISTS"})
                continue
        create_category(
            crm,
            category_code=code,
            category_name=fam["headword"],
            is_active=False,
            description=f"AUTO candidate; phrases: {', '.join(fam['phrases'][:5])}",
            updated_by="AUTO_CANDIDATE",
        )
        with crm.cursor() as cur:
            cur.execute(
                "update crm_product_categories set category_kind='PRODUCT',"
                " lifecycle_state='DRAFT' where category_code=%s",
                (code,),
            )
        crm.commit()
        created.append({"family": fam["headword"], "category_code": code,
                        "action": "CREATED"})
    return created


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--promote", action="store_true",
                    help="run phase C (writes categories); default is dry run")
    ap.add_argument("--scope", default="DEFAULT")
    ap.add_argument("--min-proc", type=int, default=None)
    ap.add_argument("--min-occ", type=int, default=None)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    crm = connect_crm()
    di = connect_di()
    try:
        cfg = load_config(crm, args.scope)
        min_proc = args.min_proc or cfg["min_distinct_procurements"]
        min_occ = args.min_occ or cfg["min_occurrences"]
        print(f"CONFIG min_proc={min_proc} min_occ={min_occ} "
              f"okpd_digits={cfg['okpd_cluster_digits']} source={cfg['_source']}")

        rows = load_candidates(di, min_proc, min_occ)
        print(f"PHASE_A_INPUT candidates={len(rows)}")
        pids = []
        for row in rows:
            prov = row.get("provenance") or {}
            if isinstance(prov, str):
                try:
                    prov = json.loads(prov)
                except Exception:
                    prov = {}
            if prov.get("procurement_id"):
                pids.append(int(prov["procurement_id"]))
        okpd_map = load_okpd_map(crm, sorted(set(pids)), cfg["okpd_cluster_digits"])
        families = phase_a(rows, okpd_map)
        print(f"PHASE_A_FAMILIES {len(families)}")

        index = load_category_index(crm)
        phase_b(families, index)
        syn = [f for f in families if f.get("synonym_state") == "SYNONYM_EXISTING"]
        new = [f for f in families if f.get("synonym_state") == "NEW"]
        print(f"PHASE_B synonym_existing={len(syn)} new={len(new)}")

        print("TOP_FAMILIES")
        for fam in families[: args.top]:
            print(f"  {fam['synonym_state']:<17} {fam['headword']:<18} "
                  f"okpd={fam['okpd_cluster'] or '-':<6} "
                  f"procs={fam['max_procurements']:<4} occ={fam['occurrences']:<6} "
                  f"phrases={len(fam['phrases'])} "
                  f"match={fam.get('matched_category', '')}")

        result = phase_c(crm, families, cfg, apply=args.promote)
        print(f"PHASE_C mode={'PROMOTE' if args.promote else 'DRY_RUN'} "
              f"candidates={len(result)}")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
