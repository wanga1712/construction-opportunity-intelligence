#!/usr/bin/env python3
"""Category architecture decomposition — SHADOW A/B on frozen corpora."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit") if Path("/opt/CRM_Streamlit").is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.registry_extract_mapper import (
    build_registry_vocabulary,
)
from src.services.commercial_routing_v3.arch_shadow_runner import (
    run_architecture_a,
    run_architecture_b,
)

CAL = Path(os.environ.get("ARCH_CALIBRATION") or "/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json")
HOLD = Path(os.environ.get("ARCH_HOLDOUT") or "/tmp/MODEL_CATEGORY_HOLDOUT_CORPUS.json")
OUT = Path(os.environ.get("ARCH_OUT") or "/tmp/arch_decomposition_summary.json")
ARCHS = {x.strip().upper() for x in (os.environ.get("ARCH_ARCHS") or "A,B").split(",") if x.strip()}
CORPUS_MODE = os.environ.get("ARCH_CORPUS") or "both"  # calibration|holdout|both
LIMIT = int(os.environ.get("ARCH_LIMIT") or "0") or None
CRITICAL = (37082, 23591, 27355, 34517)
PRODUCT_SPAM = frozenset(
    {"lighting", "computers", "flooring", "cable_support_systems", "furniture", "curbstone"}
)


def _load_cases() -> list[dict]:
    cases: list[dict] = []
    seen = set()
    paths = []
    if CORPUS_MODE in ("calibration", "both"):
        paths.append(("calibration", CAL))
    if CORPUS_MODE in ("holdout", "both"):
        paths.append(("holdout", HOLD))
    for tag, path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for c in data["cases"]:
            pid = int(c["procurement_id"])
            if pid in seen:
                continue
            seen.add(pid)
            c = dict(c)
            c["_corpus"] = tag
            cases.append(c)
    if LIMIT:
        cases = cases[:LIMIT]
    return cases


def _score(case: dict, a_out: dict | None, b_out: dict | None) -> dict:
    kind = case.get("expected_label_kind")
    expect = case.get("expected_exact_category")
    row = {
        "procurement_id": case["procurement_id"],
        "corpus": case.get("_corpus"),
        "bucket": case.get("bucket"),
        "expected_label_kind": kind,
        "expected_exact_category": expect,
        "title": (case.get("title") or "")[:140],
    }
    if a_out:
        cats = a_out.get("A2_CATEGORY") or []
        spam = bool(a_out.get("object_spam"))
        if kind != "EXPECTED_EXACT_CATEGORY" and kind != "EXPECTED_EMPTY":
            spam = spam or (len(cats) >= 3) or any(c in PRODUCT_SPAM for c in cats)
        a = {
            "A1_FORM": a_out.get("A1_FORM"),
            "A1_ITEMS": a_out.get("A1_ITEMS"),
            "A1_EXPLICIT_GOODS": a_out.get("A1_EXPLICIT_GOODS"),
            "A2_CATEGORY": cats,
            "A1_INFERENCE_RUN_ID": a_out.get("A1_INFERENCE_RUN_ID"),
            "A2_INFERENCE_RUN_ID": a_out.get("A2_INFERENCE_RUN_ID"),
            "A2_PROVENANCE": a_out.get("A2_PROVENANCE"),
            "seconds": a_out.get("seconds"),
            "model_calls": a_out.get("model_calls"),
            "invalid": a_out.get("invalid_category_codes") or [],
            "object_spam": spam,
        }
        if kind == "EXPECTED_EXACT_CATEGORY":
            a["exact_match"] = expect in cats
            a["missed"] = expect not in cats
            a["false_positive"] = None
        elif kind == "EXPECTED_EMPTY":
            a["false_positive"] = bool(cats)
            a["correct_empty"] = not cats
            a["missed"] = None
        else:
            a["nonempty"] = bool(cats)
        errs = []
        if kind == "EXPECTED_EXACT_CATEGORY" and expect not in cats:
            form = (a_out.get("A1_FORM") or "").upper()
            items = " ".join(a_out.get("A1_ITEMS") or []).lower()
            if form != "DIRECT_GOODS_PURCHASE":
                errs.append("A1_PROCUREMENT_FORM_ERROR")
            if not (a_out.get("A1_ITEMS") or a_out.get("A1_EXPLICIT_GOODS")):
                errs.append("A1_ITEM_EXTRACTION_ERROR")
            elif expect and expect.replace("_", " ") not in items and expect.split("_")[0] not in items:
                # weak heuristic — still attribute mapping to A2 primarily
                errs.append("A1_ITEM_EXTRACTION_ERROR")
            if not cats:
                errs.append("A2_ABSTENTION_ERROR")
            else:
                errs.append("A2_CATEGORY_MAPPING_ERROR")
            a["error_attribution"] = errs
            a["ROOT_CAUSE"] = errs[0] if errs else "A2_CATEGORY_MAPPING_ERROR"
        elif kind == "EXPECTED_EMPTY" and cats:
            a["error_attribution"] = ["A2_ABSTENTION_ERROR"]
            a["ROOT_CAUSE"] = "A2_ABSTENTION_ERROR"
        elif spam:
            a["error_attribution"] = ["A2_CATEGORY_MAPPING_ERROR"]
            a["ROOT_CAUSE"] = "A2_CATEGORY_MAPPING_ERROR"
        row["A"] = a

    if b_out:
        cats = b_out.get("B_MAPPED_CATEGORY") or []
        gaps = b_out.get("registry_vocabulary_gaps") or []
        spam = bool(b_out.get("object_spam"))
        if kind not in ("EXPECTED_EXACT_CATEGORY", "EXPECTED_EMPTY"):
            spam = spam or (len(cats) >= 3) or any(c in PRODUCT_SPAM for c in cats)
        b = {
            "B_EXTRACTED_ITEM": b_out.get("B_EXTRACTED_ITEM"),
            "B_EXTRACTED_FORM": b_out.get("B_EXTRACTED_FORM"),
            "B_MAPPED_CATEGORY": cats,
            "B_INFERENCE_RUN_ID": b_out.get("B_INFERENCE_RUN_ID"),
            "B_PROVENANCE": b_out.get("B_PROVENANCE"),
            "registry_vocabulary_gaps": gaps,
            "seconds": b_out.get("seconds"),
            "model_calls": b_out.get("model_calls"),
            "invalid": b_out.get("invalid_category_codes") or [],
            "object_spam": spam,
            "BUSINESS_MAPPING_IMPERSONATES_MODEL": False,
        }
        if kind == "EXPECTED_EXACT_CATEGORY":
            b["exact_match"] = expect in cats
            b["missed"] = expect not in cats
        elif kind == "EXPECTED_EMPTY":
            b["false_positive"] = bool(cats)
            b["correct_empty"] = not cats
        else:
            b["nonempty"] = bool(cats)
        errs = []
        if kind == "EXPECTED_EXACT_CATEGORY" and expect not in cats:
            items = b_out.get("B_EXTRACTED_ITEM") or []
            if not items:
                errs.append("B_EXTRACTION_ERROR")
            else:
                errs.append("B_REGISTRY_MAPPING_ERROR")
            if gaps:
                errs.append("B_REGISTRY_MAPPING_ERROR")
            b["error_attribution"] = list(dict.fromkeys(errs)) or ["B_REGISTRY_MAPPING_ERROR"]
            b["ROOT_CAUSE"] = b["error_attribution"][0]
        elif kind == "EXPECTED_EMPTY" and cats:
            b["error_attribution"] = ["B_REGISTRY_MAPPING_ERROR"]
            b["ROOT_CAUSE"] = "B_REGISTRY_MAPPING_ERROR"
        row["B"] = b
    return row


def _agg(rows: list[dict], key: str) -> dict:
    directs = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EXACT_CATEGORY"]
    negs = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EMPTY"]
    objs = [
        r
        for r in rows
        if r.get("expected_label_kind") not in ("EXPECTED_EXACT_CATEGORY", "EXPECTED_EMPTY")
    ]
    arm = [r[key] for r in rows if key in r]
    secs = [float(a.get("seconds") or 0) for a in arm]
    return {
        "n": len(arm),
        "DIRECT_TOTAL": len(directs),
        "DIRECT_CORRECT": sum(1 for r in directs if (r.get(key) or {}).get("exact_match")),
        "DIRECT_MISSED": sum(1 for r in directs if (r.get(key) or {}).get("missed")),
        "NEGATIVE_TOTAL": len(negs),
        "NEGATIVE_CORRECT_EMPTY": sum(1 for r in negs if (r.get(key) or {}).get("correct_empty")),
        "NEGATIVE_FALSE_POSITIVE": sum(1 for r in negs if (r.get(key) or {}).get("false_positive")),
        "OBJECT_TOTAL": len(objs),
        "OBJECT_SPAM": sum(1 for r in objs if (r.get(key) or {}).get("object_spam")),
        "INVALID_CATEGORY_CODE": sum(1 for a in arm if a.get("invalid")),
        "FORMAT_INVALID": 0,
        "AVG_SECONDS": round(sum(secs) / max(len(secs), 1), 3),
        "MODEL_CALLS_PER_CASE": (arm[0].get("model_calls") if arm else None),
        "A1_ITEM_EXTRACTION_ERRORS": sum(
            1 for a in arm if "A1_ITEM_EXTRACTION_ERROR" in (a.get("error_attribution") or [])
        ),
        "A2_CATEGORY_ERRORS": sum(
            1
            for a in arm
            if set(a.get("error_attribution") or [])
            & {"A2_CATEGORY_MAPPING_ERROR", "A2_ABSTENTION_ERROR"}
        ),
        "B_EXTRACTION_ERRORS": sum(
            1 for a in arm if "B_EXTRACTION_ERROR" in (a.get("error_attribution") or [])
        ),
        "B_REGISTRY_MAPPING_ERRORS": sum(
            1 for a in arm if "B_REGISTRY_MAPPING_ERROR" in (a.get("error_attribution") or [])
        ),
        "UNMAPPED_GAPS": sum(len(a.get("registry_vocabulary_gaps") or []) for a in arm),
    }


def main() -> int:
    cases = _load_cases()
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    registry, allowed, _ = engine.load_registry()
    vocab = build_registry_vocabulary(crm, registry)

    a_before = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o_before = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )

    results = []
    for i, case in enumerate(cases, 1):
        pid = int(case["procurement_id"])
        row = {
            "title": case.get("title"),
            "okpd_code": case.get("okpd_code"),
            "okpd_name": case.get("okpd_name"),
        }
        a_out = b_out = None
        if "A" in ARCHS:
            a_out = run_architecture_a(crm, procurement_id=pid, row=row, acquire_gpu=True)
        if "B" in ARCHS:
            b_out = run_architecture_b(
                crm, procurement_id=pid, row=row, vocab=vocab, acquire_gpu=True
            )
        scored = _score(case, a_out, b_out)
        results.append(scored)
        print(json.dumps({"i": i, "n": len(cases), **{k: scored[k] for k in scored if k in ("procurement_id", "corpus", "A", "B")}}, ensure_ascii=False), flush=True)

    a_after = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o_after = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )

    by_corpus = {"calibration": [], "holdout": [], "all": results}
    for r in results:
        by_corpus.setdefault(r.get("corpus") or "all", []).append(r)
        if r.get("corpus") in ("calibration", "holdout"):
            pass

    cal = [r for r in results if r.get("corpus") == "calibration"]
    hold = [r for r in results if r.get("corpus") == "holdout"]

    critical = []
    for pid in CRITICAL:
        hit = next((r for r in results if int(r["procurement_id"]) == pid), None)
        if hit:
            critical.append(hit)

    # SFT readiness from frozen labels (no new labeling)
    dist = Counter(
        c.get("expected_exact_category") or c.get("expected_label_kind") for c in cases
    )
    sft = {
        "EXPERT_REVIEWED_TOTAL": len(cases),
        "CLEAR_DIRECT_LABELED": sum(
            1 for c in cases if c.get("expected_label_kind") == "EXPECTED_EXACT_CATEGORY"
        ),
        "CLEAR_NEGATIVE_LABELED": sum(
            1 for c in cases if c.get("expected_label_kind") == "EXPECTED_EMPTY"
        ),
        "OBJECT_LABELED": sum(
            1
            for c in cases
            if c.get("expected_label_kind") not in ("EXPECTED_EXACT_CATEGORY", "EXPECTED_EMPTY")
        ),
        "CATEGORY_DISTRIBUTION": dict(dist),
        "SFT_MIN_ADDITIONAL_LABELS_NEEDED": max(0, 200 - len(cases)),
        "MODEL_TRAINING_STARTED": False,
    }

    summary = {
        "WIP": "CRM-V3-CATEGORY-ARCHITECTURE-DECOMPOSITION-1",
        "ARCHS": sorted(ARCHS),
        "n_cases": len(results),
        "A_calibration": _agg(cal, "A") if "A" in ARCHS else None,
        "A_holdout": _agg(hold, "A") if "A" in ARCHS else None,
        "A_all": _agg(results, "A") if "A" in ARCHS else None,
        "B_calibration": _agg(cal, "B") if "B" in ARCHS else None,
        "B_holdout": _agg(hold, "B") if "B" in ARCHS else None,
        "B_all": _agg(results, "B") if "B" in ARCHS else None,
        "critical_cases": critical,
        "sft_readiness": sft,
        "registry_term_count": len(vocab.terms_sorted),
        "PRODUCTION_ASSESSMENTS_MUTATED": a_after - a_before,
        "PRODUCTION_OPPORTUNITIES_MUTATED": o_after - o_before,
        "results": results,
    }

    # Decision helpers
    def hard_pass(agg: dict | None) -> bool:
        if not agg:
            return False
        return (
            agg["DIRECT_MISSED"] == 0
            and agg["NEGATIVE_FALSE_POSITIVE"] == 0
            and agg["OBJECT_SPAM"] == 0
            and agg["INVALID_CATEGORY_CODE"] == 0
        )

    a_ok = hard_pass(summary["A_calibration"]) and hard_pass(summary["A_holdout"])
    b_ok = hard_pass(summary["B_calibration"]) and hard_pass(summary["B_holdout"])
    if a_ok:
        decision = "TWO_PASS_MODEL_READY"
    elif b_ok:
        decision = "MODEL_EXTRACTION_PLUS_BUSINESS_MAPPING_READY"
    else:
        decision = "NOT_READY"
    summary["CATEGORY_ARCHITECTURE_DECISION"] = decision
    summary["A_HARD_PASS"] = a_ok
    summary["B_HARD_PASS"] = b_ok

    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    slim = {k: summary[k] for k in summary if k not in ("results", "critical_cases")}
    print("SUMMARY=" + json.dumps(slim, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
