#!/usr/bin/env python3
"""Phase 7 focused re-AB: v5 vs v6_1 on clear directs/negatives after label fixes."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

# Reuse scoring from main AB by importing after path setup
sys.path.insert(0, "/tmp")
# Inline minimal runner
from src.services.db_bootstrap import connect_databases
from src.services.crm_ai_assessment_runner import ensure_v3_model_input
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.model_input import model_input_as_prompt_procurement
from src.services.commercial_routing_v3.procurement_form import classify_procurement_form
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION as V5
from src.services.commercial_routing_v3.prompt_v6 import PROMPT_VERSION as V6, build_v6_prompt
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference

CORPUS = Path("/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json")


def _hyps(val):
    if not isinstance(val, dict):
        return []
    h = val.get("commercial_category_hypotheses") or []
    return h if isinstance(h, list) else []


def _cats(hyps):
    return [str(h["category_code"]) for h in hyps if isinstance(h, dict) and h.get("category_code")]


def score(case, out, allowed):
    val = out.get("validated_model_result") or {}
    cats = _cats(_hyps(val))
    invalid = [c for c in cats if c not in allowed]
    kind = case["expected_label_kind"]
    expect = case.get("expected_exact_category")
    row = {
        "procurement_id": case["procurement_id"],
        "bucket": case["bucket"],
        "expected_label_kind": kind,
        "expected_exact_category": expect,
        "prompt_version": out.get("prompt_version"),
        "inference_run_id": out.get("inference_run_id"),
        "validation_status": out.get("validation_status"),
        "categories": cats,
        "empty_hypothesis_status": val.get("empty_hypothesis_status") if isinstance(val, dict) else None,
        "invalid_category_codes": invalid,
        "nonempty": bool(cats),
        "title": (case.get("title") or "")[:120],
    }
    if kind == "EXPECTED_EXACT_CATEGORY":
        row["exact_match"] = expect in cats
        row["missed"] = expect not in cats
        row["false_positive"] = None
        row["correct_empty"] = None
    elif kind == "EXPECTED_EMPTY":
        row["exact_match"] = None
        row["missed"] = None
        row["false_positive"] = bool(cats)
        row["correct_empty"] = not cats
    else:
        row["exact_match"] = row["missed"] = row["false_positive"] = row["correct_empty"] = None
    return row


def agg(rows):
    exact = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EXACT_CATEGORY"]
    empties = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EMPTY"]
    return {
        "n": len(rows),
        "CLEAR_DIRECT_EXACT_MATCH": sum(1 for r in exact if r.get("exact_match")),
        "CLEAR_DIRECT_MISSED": sum(1 for r in exact if r.get("missed")),
        "CLEAR_DIRECT_N": len(exact),
        "CLEAR_NEGATIVE_CORRECT_EMPTY": sum(1 for r in empties if r.get("correct_empty")),
        "CLEAR_NEGATIVE_FALSE_POSITIVE": sum(1 for r in empties if r.get("false_positive")),
        "CLEAR_NEGATIVE_N": len(empties),
        "INVALID_CATEGORY_CODE": sum(len(r.get("invalid_category_codes") or []) for r in rows),
        "NONEMPTY_CATEGORY_RATE": round(sum(1 for r in rows if r.get("nonempty")) / max(1, len(rows)), 3),
    }


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = [
        c
        for c in corpus["cases"]
        if c["expected_label_kind"] in ("EXPECTED_EXACT_CATEGORY", "EXPECTED_EMPTY")
        or c["procurement_id"] in (18512, 36939, 36596, 34524, 37605, 13564)
    ]
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    _, allowed, _ = engine.load_registry()
    allowed_set = set(allowed)
    results = {"v5": [], "v6_1": []}
    a0 = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o0 = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )

    for i, case in enumerate(cases, 1):
        pid = int(case["procurement_id"])
        rows = crm.execute_query("SELECT * FROM crm_procurements WHERE id=%s", (pid,))
        if not rows:
            continue
        row = dict(rows[0])
        try:
            mi = ensure_v3_model_input(row, crm)
            procurement = model_input_as_prompt_procurement(mi)
            procurement["v3_model_input"] = mi
        except Exception:
            mi = None
            procurement = {
                "title": row.get("auction_name"),
                "okpd_code": row.get("okpd_code"),
                "okpd_name": row.get("okpd_name"),
                "price": float(row.get("initial_price") or 0),
            }
        for label, ver in (("v5", V5), ("v6_1", V6)):
            if ver == V6:
                prompt = build_v6_prompt(
                    procurement,
                    registry=engine.load_registry()[0],
                    okpd_priors=engine._load_priors(),
                    routing_signals=[],
                    procurement_form_prior=classify_procurement_form(procurement).value,
                )
            else:
                prompt = engine.build_prompt_context(procurement)
            out = run_shadow_inference(
                crm,
                procurement_id=pid,
                procurement=procurement,
                model_input=mi if isinstance(mi, dict) else None,
                acquire_gpu=True,
                dry_run_persist=False,
                compute_business_preview=False,
                prompt_version=ver,
                prompt_text=prompt,
            )
            if out.get("inference_run_id"):
                ir = crm.execute_query(
                    "SELECT validated_model_result, prompt_version, validation_status FROM crm_v3_model_inference_runs WHERE id=%s",
                    (out["inference_run_id"],),
                )
                if ir:
                    out["validated_model_result"] = ir[0].get("validated_model_result")
                    out["prompt_version"] = ir[0].get("prompt_version")
                    out["validation_status"] = ir[0].get("validation_status")
            scored = score(case, out, allowed_set)
            results[label].append(scored)
            print(json.dumps({"i": i, "arm": label, **scored}, ensure_ascii=False), flush=True)

    a1 = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o1 = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )
    summary = {
        "PROMPT_VERSION_OLD": V5,
        "PROMPT_VERSION_NEW": V6,
        "cases_run": len(cases),
        "v5": agg(results["v5"]),
        "v6_1": agg(results["v6_1"]),
        "PRODUCTION_ASSESSMENTS_MUTATED": a1 - a0,
        "PRODUCTION_OPPORTUNITIES_MUTATED": o1 - o0,
        "results": results,
    }
    Path("/tmp/phase7_ab_v61_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("SUMMARY=" + json.dumps({k: summary[k] for k in summary if k != "results"}, ensure_ascii=False))
    ok = (
        summary["PRODUCTION_ASSESSMENTS_MUTATED"] == 0
        and summary["v6_1"]["INVALID_CATEGORY_CODE"] == 0
        and summary["v6_1"]["CLEAR_DIRECT_MISSED"] == 0
        and summary["v6_1"]["CLEAR_NEGATIVE_FALSE_POSITIVE"] == 0
    )
    print("PHASE7_AB_V61=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
