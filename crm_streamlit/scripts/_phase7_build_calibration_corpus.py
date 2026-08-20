#!/usr/bin/env python3
"""Build Phase 7 calibration corpus — human-defensible labels, not Python priors."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit") if Path("/opt/CRM_Streamlit").is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)
from src.services.db_bootstrap import connect_databases

# OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH=NO
DIRECT_EXCLUDE = r"(ремонт|содержани|обслуживан|строительств|монтаж|благоустрой|работ\s+по|услуг)"
DIRECT_INCLUDE = r"(поставк|закупк|приобретен|поставка)"


def _pick(crm, product_pat: str, limit: int, *, require_supply: bool) -> list[dict]:
    if require_supply:
        sql = """
        SELECT id, auction_name, okpd_code, okpd_name, initial_price, crm_stage
        FROM crm_procurements
        WHERE auction_name ~* %s
          AND auction_name ~* %s
          AND auction_name !~* %s
        ORDER BY id DESC
        LIMIT %s
        """
        rows = crm.execute_query(sql, (product_pat, DIRECT_INCLUDE, DIRECT_EXCLUDE, limit))
    else:
        sql = """
        SELECT id, auction_name, okpd_code, okpd_name, initial_price, crm_stage
        FROM crm_procurements
        WHERE auction_name ~* %s
        ORDER BY id DESC
        LIMIT %s
        """
        rows = crm.execute_query(sql, (product_pat, limit))
    return [dict(r) for r in (rows or [])]


DIRECT_PATS = [
    (r"светильн|прожектор|светодиодн", "lighting"),
    (r"ноутбук|моноблок|персональн(ый|ых)\s+компьютер", "computers"),
    (r"гидроизоляц", "waterproofing"),
    (r"бордюр|бортовой\s+камень|поребрик", "curbstone"),
    (r"дренажн|ливневая\s+канализац", "drainage_water_management"),
    (r"кабельн(ый|ые)\s+лотк|кабеленесущ", "cable_support_systems"),
    (r"линолеум|ламинат|паркетн", "flooring"),
]

NEGATIVE_PATS = [
    r"офтальмолог|медицинск(ое|ого)\s+оборуд",
    r"газ(овый|овых)\s+счетчик|теплосчетчик",
    r"лабораторн(ое|ых)\s+оборуд",
    r"лекарств|фармацевт",
    r"автомобил(ь|я|ей)\s+(легков|грузов)",
    r"охран(а|ы)\s+(объект|террито|услуг)",
    r"пищев(ые|ых)\s+продукт",
    r"учебн(ик|ые\s+пособи)",
    r"мебел(ь|и)\s+(офис|школ|медицин)",
    r"канцелярск",
    r"дезинфекц",
    r"огнетушител",
    r"спецодежд",
    r"страхован",
    r"транспортн(ые|ых)\s+услуг",
]

OBJECT_PATS = [
    r"автомобильн(ой|ых)\s+дорог",
    r"капитальн(ый|ого)\s+ремонт\s+мост",
    r"ремонт\s+мост|путепровод",
    r"капитальн(ый|ого)\s+ремонт.*школ",
    r"тротуар",
    r"содержани[ея]\s+.*дорог",
    r"строительств.*здани",
    r"спортивн(ой|ая)\s+(площадк|поле)",
]

PRIOR11 = [720, 886, 949, 975, 1016, 6374, 8003, 8175, 10795, 10812, 13688]


def main() -> int:
    _, _, crm, _ = connect_databases()
    cases = []
    seen = set()

    def add(bucket, row, expected_cat, label_kind, note=""):
        pid = int(row["id"])
        if pid in seen:
            return False
        seen.add(pid)
        cases.append(
            {
                "procurement_id": pid,
                "bucket": bucket,
                "title": row.get("auction_name"),
                "okpd_code": row.get("okpd_code"),
                "okpd_name": row.get("okpd_name"),
                "expected_label_kind": label_kind,
                "expected_exact_category": expected_cat,
                "label_note": note,
                "OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH": False,
            }
        )
        return True

    for pat, cat in DIRECT_PATS:
        for row in _pick(crm, pat, 6, require_supply=True):
            add(
                "CLEAR_DIRECT_POSITIVE",
                row,
                cat,
                "EXPECTED_EXACT_CATEGORY",
                "title supply+product; unambiguous registry map",
            )
            if sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE") >= 16:
                break
        if sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE") >= 16:
            break

    # Fallback: if supply+product too rare, allow product-named titles without repair/maintenance
    if sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE") < 15:
        for pat, cat in DIRECT_PATS:
            sql = """
            SELECT id, auction_name, okpd_code, okpd_name
            FROM crm_procurements
            WHERE auction_name ~* %s AND auction_name !~* %s
            ORDER BY id DESC LIMIT 8
            """
            rows = crm.execute_query(sql, (pat, DIRECT_EXCLUDE))
            for row in rows or []:
                add(
                    "CLEAR_DIRECT_POSITIVE",
                    dict(row),
                    cat,
                    "EXPECTED_EXACT_CATEGORY",
                    "product-named title; repair/maintenance excluded",
                )
                if sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE") >= 16:
                    break
            if sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE") >= 16:
                break

    for pat in NEGATIVE_PATS:
        for row in _pick(crm, pat, 4, require_supply=False):
            # Skip if title also names a registry product strongly
            title = (row.get("auction_name") or "").lower()
            if any(x in title for x in ("светиль", "ноутбук", "гидроизол", "бордюр", "дренаж")):
                continue
            add(
                "CLEAR_NEGATIVE",
                row,
                None,
                "EXPECTED_EMPTY",
                "outside sellable registry product/service",
            )
            if sum(1 for c in cases if c["bucket"] == "CLEAR_NEGATIVE") >= 16:
                break
        if sum(1 for c in cases if c["bucket"] == "CLEAR_NEGATIVE") >= 16:
            break

    for pat in OBJECT_PATS:
        for row in _pick(crm, pat, 5, require_supply=False):
            add(
                "OBJECT_CONSTRUCTION",
                row,
                None,
                "AMBIGUOUS_REVIEW",
                "object/construction; contextual hyps optional; no forced drainage",
            )
            if sum(1 for c in cases if c["bucket"] == "OBJECT_CONSTRUCTION") >= 16:
                break
        if sum(1 for c in cases if c["bucket"] == "OBJECT_CONSTRUCTION") >= 16:
            break

    for pid in PRIOR11:
        if pid in seen:
            # retag existing as also diagnostic
            for c in cases:
                if c["procurement_id"] == pid:
                    c["also_prior11_diagnostic"] = True
            continue
        rows = crm.execute_query(
            "SELECT id, auction_name, okpd_code, okpd_name FROM crm_procurements WHERE id=%s",
            (pid,),
        )
        if not rows:
            continue
        add("PRIOR11_DIAGNOSTIC", dict(rows[0]), None, "AMBIGUOUS_REVIEW", "diagnostic vs old python prior only")

    # Road-family review pack (explicit)
    ROAD_EXTRA = [
        (r"защитн.*сло.*дорог|слой\s+износа", "road protective layers"),
        (r"ремонт\s+мост", "bridge repair"),
        (r"ремонт\s+.*автомобильн.*дорог", "road repair"),
        (r"содержани[ея]\s+.*дорог", "road maintenance"),
        (r"тротуар", "sidewalks"),
        (r"спортивн(ой|ая)\s+(площадк|поле)", "sports field"),
    ]
    for pat, label in ROAD_EXTRA:
        for row in _pick(crm, pat, 2, require_supply=False):
            if add(
                "ROAD_CASE_REVIEW",
                row,
                None,
                "AMBIGUOUS_REVIEW",
                f"road-family review: {label}",
            ):
                break

    summary = {
        "wip": "CRM-V3-MODEL-AUTHORITY-RESTORATION-1",
        "phase": "7",
        "OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH": False,
        "CALIBRATION_CASES": len(cases),
        "CLEAR_DIRECT_POSITIVES": sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE"),
        "CLEAR_NEGATIVES": sum(1 for c in cases if c["bucket"] == "CLEAR_NEGATIVE"),
        "OBJECT_CASES": sum(1 for c in cases if c["bucket"] == "OBJECT_CONSTRUCTION"),
        "PRIOR11_DIAGNOSTIC": sum(
            1
            for c in cases
            if c["bucket"] == "PRIOR11_DIAGNOSTIC" or c.get("also_prior11_diagnostic")
        ),
        "ROAD_CASE_REVIEW": sum(1 for c in cases if c["bucket"] == "ROAD_CASE_REVIEW"),
        "cases": cases,
    }
    out = Path("/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "cases"}, ensure_ascii=False, indent=2))
    print("WROTE", out)
    return 0 if len(cases) >= 45 and summary["CLEAR_DIRECT_POSITIVES"] >= 15 else 1


if __name__ == "__main__":
    raise SystemExit(main())
