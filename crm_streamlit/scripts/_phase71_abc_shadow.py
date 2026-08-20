#!/usr/bin/env python3
"""Phase 7.1 A/B/C SHADOW on calibration corpus: v5 vs v6_1 vs v6_2."""
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
from src.services.crm_ai_assessment_runner import ensure_v3_model_input
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.model_input import model_input_as_prompt_procurement
from src.services.commercial_routing_v3.procurement_form import classify_procurement_form
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION as V5
from src.services.commercial_routing_v3.prompt_v6_1 import (
    PROMPT_VERSION as V61,
    build_v6_1_prompt,
)
from src.services.commercial_routing_v3.prompt_v6_2 import (
    PROMPT_VERSION as V62,
    build_v6_2_prompt,
)
from src.services.commercial_routing_v3.prompt_v6_3 import (
    PROMPT_VERSION as V63,
    build_v6_3_prompt,
)
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference

CORPUS = Path(os.environ.get("PHASE71_CORPUS") or "/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json")
LIMIT = int(os.environ.get("PHASE71_AB_LIMIT") or "0") or None
ARMS = os.environ.get("PHASE71_ARMS") or "v5,v6_1,v6_2"
OUT = Path(os.environ.get("PHASE71_OUT") or "/tmp/phase71_abc_summary.json")


def _hyps(val):
    if not isinstance(val, dict):
        return []
    h = val.get("commercial_category_hypotheses") or []
    return h if isinstance(h, list) else []


def _cats(hyps):
    return [str(h["category_code"]) for h in hyps if isinstance(h, dict) and h.get("category_code")]


def score(case, out, allowed):
    val = out.get("validated_model_result") or {}
    hyps = _hyps(val)
    cats = _cats(hyps)
    invalid = [c for c in cats if c not in allowed]
    kind = case.get("expected_label_kind")
    expect = case.get("expected_exact_category")
    oc = val.get("object_classification") if isinstance(val.get("object_classification"), dict) else {}
    confs = [h.get("confidence") for h in hyps if isinstance(h, dict)]
    row = {
        "procurement_id": case["procurement_id"],
        "bucket": case.get("bucket"),
        "expected_label_kind": kind,
        "expected_exact_category": expect,
        "prompt_version": out.get("prompt_version"),
        "inference_run_id": out.get("inference_run_id"),
        "validation_status": out.get("validation_status"),
        "categories": cats,
        "empty_hypothesis_status": val.get("empty_hypothesis_status") if isinstance(val, dict) else None,
        "invalid_category_codes": invalid,
        "nonempty": bool(cats),
        "procurement_form": val.get("procurement_form") if isinstance(val, dict) else None,
        "object_type": oc.get("object_type"),
        "object_subtype": oc.get("object_subtype"),
        "work_stage": oc.get("work_stage"),
        "confidences": confs,
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
        row["object_contextual"] = bool(cats)
    return row


def agg(rows):
    exact = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EXACT_CATEGORY"]
    empties = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EMPTY"]
    objects = [r for r in rows if r.get("bucket") in ("OBJECT_CONSTRUCTION", "ROAD_CASE_REVIEW", "OBJECT_RELABELED")]
    return {
        "n": len(rows),
        "FORMAT_VALID_RATE": round(
            sum(1 for r in rows if r.get("validation_status") == "VALIDATED_SUCCESS") / max(1, len(rows)), 3
        ),
        "NONEMPTY_CATEGORY_RATE": round(sum(1 for r in rows if r.get("nonempty")) / max(1, len(rows)), 3),
        "CLEAR_DIRECT_EXACT_MATCH": sum(1 for r in exact if r.get("exact_match")),
        "CLEAR_DIRECT_MISSED": sum(1 for r in exact if r.get("missed")),
        "CLEAR_DIRECT_N": len(exact),
        "CLEAR_NEGATIVE_CORRECT_EMPTY": sum(1 for r in empties if r.get("correct_empty")),
        "CLEAR_NEGATIVE_FALSE_POSITIVE": sum(1 for r in empties if r.get("false_positive")),
        "CLEAR_NEGATIVE_N": len(empties),
        "OBJECT_NONEMPTY_CONTEXTUAL": sum(1 for r in objects if r.get("nonempty")),
        "OBJECT_EMPTY": sum(1 for r in objects if not r.get("nonempty")),
        "OBJECT_N": len(objects),
        "INVALID_CATEGORY_CODE": sum(len(r.get("invalid_category_codes") or []) for r in rows),
        "HALLUCINATED_CATEGORY_CODE": sum(len(r.get("invalid_category_codes") or []) for r in rows),
        "PROCUREMENT_FORM_NONEMPTY": sum(
            1 for r in rows if r.get("procurement_form") and r.get("procurement_form") != "UNKNOWN"
        ),
        "OBJECT_TYPE_NONEMPTY": sum(1 for r in rows if r.get("object_type")),
    }


def build_prompt(engine, procurement, ver: str) -> str:
    registry, _, _ = engine.load_registry()
    priors = engine._load_priors()
    form = classify_procurement_form(procurement).value
    if ver == V63:
        return build_v6_3_prompt(
            procurement, registry=registry, okpd_priors=priors, routing_signals=[], procurement_form_prior=form
        )
    if ver == V62:
        return build_v6_2_prompt(
            procurement, registry=registry, okpd_priors=priors, routing_signals=[], procurement_form_prior=form
        )
    if ver == V61:
        return build_v6_1_prompt(
            procurement, registry=registry, okpd_priors=priors, routing_signals=[], procurement_form_prior=form
        )
    return engine.build_prompt_context(procurement)


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = list(corpus["cases"])
    if LIMIT:
        cases = cases[:LIMIT]
    arm_map = {"v5": V5, "v6_1": V61, "v6_2": V62, "v6_3": V63}
    arms = [a.strip() for a in ARMS.split(",") if a.strip() in arm_map]
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    _, allowed, _ = engine.load_registry()
    allowed_set = set(allowed)
    results = {a: [] for a in arms}
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
        for arm in arms:
            ver = arm_map[arm]
            prompt = build_prompt(engine, procurement, ver)
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
            results[arm].append(scored)
            print(json.dumps({"i": i, "arm": arm, **scored}, ensure_ascii=False), flush=True)

    a1 = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o1 = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )
    summary = {
        "PROMPT_VERSION_A": V5,
        "PROMPT_VERSION_B": V61,
        "PROMPT_VERSION_C": V62,
        "PROMPT_VERSION_D": V63,
        "CALIBRATION_CASES_RUN": len(cases),
        "arms": {a: agg(results[a]) for a in arms},
        "PRODUCTION_ASSESSMENTS_MUTATED": a1 - a0,
        "PRODUCTION_OPPORTUNITIES_MUTATED": o1 - o0,
        "results": results,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("SUMMARY=" + json.dumps({k: summary[k] for k in summary if k != "results"}, ensure_ascii=False))
    # Prefer latest candidate arm present among v6_3/v6_2
    cand = summary["arms"].get("v6_3") or summary["arms"].get("v6_2") or {}
    ok = (
        summary["PRODUCTION_ASSESSMENTS_MUTATED"] == 0
        and summary["PRODUCTION_OPPORTUNITIES_MUTATED"] == 0
        and cand.get("INVALID_CATEGORY_CODE", 0) == 0
        and cand.get("CLEAR_DIRECT_MISSED", 1) == 0
        and cand.get("CLEAR_NEGATIVE_FALSE_POSITIVE", 1) == 0
    )
    print("PHASE71_ABC=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
