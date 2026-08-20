#!/usr/bin/env python3
"""Build Phase 7.1 fresh holdout corpus (>=24 new cases, not in calibration)."""
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

CAL = Path("/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json")
OUT = Path("/tmp/MODEL_CATEGORY_HOLDOUT_CORPUS.json")

DIRECT_EXCLUDE = r"(ремонт|содержани|обслуживан|строительств|монтаж|благоустрой|работ\s+по|услуг|поверк)"
DIRECT_INCLUDE = r"(поставк|закупк|приобретен)"

DIRECT_PATS = [
    (r"светильн|лампа\s+светодиод", "lighting"),
    (r"ноутбук|моноблок|персональн(ый|ых)\s+компьютер", "computers"),
    (r"гидроизоляц", "waterproofing"),
    (r"линолеум|ламинат", "flooring"),
    (r"дренажн|ливнев", "drainage_water_management"),
    (r"кабельн(ый|ые)\s+лотк|кабеленесущ", "cable_support_systems"),
]
NEG_PATS = [
    r"поверк.*счетчик",
    r"лабораторн(ое|ых)\s+оборуд",
    r"лекарств|фармацевт(?!ическ.*институт)",  # avoid institute-name trap when possible
    r"охран(а|ы)\s+(объект|услуг)",
    r"канцелярск",
    r"транспортн(ые|ых)\s+услуг",
    r"дезинфекц",
    r"учебн(ик|ые\s+пособи)",
]
OBJ_PATS = [
    r"капитальн(ый|ого)\s+ремонт\s+мост",
    r"ремонт\s+автомобильн.*дорог",
    r"содержани[ея]\s+.*дорог",
    r"тротуар",
    r"спортивн(ой|ая)\s+(площадк|поле)",
    r"строительств.*здани",
]


def main() -> int:
    cal = json.loads(CAL.read_text(encoding="utf-8")) if CAL.is_file() else {"cases": []}
    seen = {int(c["procurement_id"]) for c in cal.get("cases", [])}
    _, _, crm, _ = connect_databases()
    cases = []

    def add(bucket, row, cat, kind, note):
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
                "expected_label_kind": kind,
                "expected_exact_category": cat,
                "label_note": note,
                "OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH": False,
                "holdout": True,
            }
        )
        return True

    for pat, cat in DIRECT_PATS:
        rows = crm.execute_query(
            """
            SELECT id, auction_name, okpd_code, okpd_name FROM crm_procurements
            WHERE auction_name ~* %s AND auction_name ~* %s AND auction_name !~* %s
            ORDER BY id ASC LIMIT 20
            """,
            (pat, DIRECT_INCLUDE, DIRECT_EXCLUDE),
        )
        for row in rows or []:
            if add(
                "CLEAR_DIRECT_POSITIVE",
                dict(row),
                cat,
                "EXPECTED_EXACT_CATEGORY",
                "holdout supply+product; unambiguous",
            ):
                if sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE") >= 8:
                    break
        if sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE") >= 8:
            break

    for pat in NEG_PATS:
        rows = crm.execute_query(
            """
            SELECT id, auction_name, okpd_code, okpd_name FROM crm_procurements
            WHERE auction_name ~* %s
            ORDER BY id ASC LIMIT 15
            """,
            (pat,),
        )
        for row in rows or []:
            title = (row.get("auction_name") or "").lower()
            if any(x in title for x in ("светиль", "ноутбук", "моноблок", "линолеум", "гидроизол", "дренаж", "ливнев")):
                continue
            if add(
                "CLEAR_NEGATIVE",
                dict(row),
                None,
                "EXPECTED_EMPTY",
                "holdout outside sellable registry product/service",
            ):
                if sum(1 for c in cases if c["bucket"] == "CLEAR_NEGATIVE") >= 8:
                    break
        if sum(1 for c in cases if c["bucket"] == "CLEAR_NEGATIVE") >= 8:
            break

    for pat in OBJ_PATS:
        rows = crm.execute_query(
            """
            SELECT id, auction_name, okpd_code, okpd_name FROM crm_procurements
            WHERE auction_name ~* %s
            ORDER BY id ASC LIMIT 15
            """,
            (pat,),
        )
        for row in rows or []:
            if add(
                "OBJECT_CONSTRUCTION",
                dict(row),
                None,
                "AMBIGUOUS_REVIEW",
                "holdout object/construction; contextual optional; no forced drainage",
            ):
                if sum(1 for c in cases if c["bucket"] == "OBJECT_CONSTRUCTION") >= 8:
                    break
        if sum(1 for c in cases if c["bucket"] == "OBJECT_CONSTRUCTION") >= 8:
            break

    summary = {
        "wip": "CRM-V3-MODEL-AUTHORITY-RESTORATION-1",
        "phase": "7.1",
        "FROZEN_BEFORE_V62_RUN": True,
        "OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH": False,
        "HOLDOUT_CASES": len(cases),
        "CLEAR_DIRECT_POSITIVES": sum(1 for c in cases if c["bucket"] == "CLEAR_DIRECT_POSITIVE"),
        "CLEAR_NEGATIVES": sum(1 for c in cases if c["bucket"] == "CLEAR_NEGATIVE"),
        "OBJECT_CASES": sum(1 for c in cases if c["bucket"] == "OBJECT_CONSTRUCTION"),
        "DISJOINT_FROM_CALIBRATION": True,
        "cases": cases,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "cases"}, ensure_ascii=False, indent=2))
    ok = (
        summary["HOLDOUT_CASES"] >= 24
        and summary["CLEAR_DIRECT_POSITIVES"] >= 8
        and summary["CLEAR_NEGATIVES"] >= 8
        and summary["OBJECT_CASES"] >= 8
    )
    print("HOLDOUT_BUILD=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
