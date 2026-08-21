#!/usr/bin/env python3
"""Phase 7.2 — T-lite vs Qwen SHADOW bake-off on frozen v6_1 prompt.

MODEL change only. Production model/prompt untouched. No fine-tune.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
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
from src.services.commercial_routing_v3.prompt_v6_1 import (
    NUM_PREDICT,
    PROMPT_VERSION as V61,
    build_v6_1_prompt,
)
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference

HOLDOUT = Path(
    os.environ.get(
        "PHASE72_HOLDOUT",
        "/tmp/MODEL_CATEGORY_HOLDOUT_CORPUS.json",
    )
)
CALIBRATION = Path(
    os.environ.get(
        "PHASE72_CALIBRATION",
        "/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json",
    )
)
T_LITE_MODEL = os.environ.get(
    "T_LITE_MODEL_ID",
    "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M",
)
QWEN_MODEL = os.environ.get("QWEN_BASELINE_MODEL", "qwen2.5:7b")
MODE = os.environ.get("PHASE72_MODE", "screening")  # screening | full | holdout
OUT_PATH = Path(os.environ.get("PHASE72_OUT", f"/tmp/phase72_t_lite_{MODE}.json"))
# Default ON: T-lite uses /api/chat where Ollama format=json works.
# Qwen arm still uses production /api/generate + format=json.
FORMAT_JSON = os.environ.get("PHASE72_FORMAT_JSON", "1") == "1"
# both | t_lite | qwen — allow T-lite-only when Qwen baseline already frozen
ARMS = os.environ.get("PHASE72_ARMS", "both").strip().lower()
RESIDUAL_IDS = (37082, 23591, 27355, 34517)
PRODUCT_SPAM_CODES = frozenset(
    {
        "lighting",
        "computers",
        "flooring",
        "cable_support_systems",
        "curbstone",
        "furniture",
    }
)


def _hyps(val):
    if not isinstance(val, dict):
        return []
    h = val.get("commercial_category_hypotheses") or []
    return h if isinstance(h, list) else []


def _cats(hyps):
    return [str(h["category_code"]) for h in hyps if isinstance(h, dict) and h.get("category_code")]


def _conf(hyps):
    vals = []
    for h in hyps:
        if isinstance(h, dict) and h.get("confidence") is not None:
            try:
                vals.append(float(h["confidence"]))
            except (TypeError, ValueError):
                pass
    return vals


def _reasons(hyps):
    out = []
    for h in hyps:
        if not isinstance(h, dict):
            continue
        rc = h.get("reason_codes") or h.get("reasons") or []
        if isinstance(rc, list):
            out.extend(str(x) for x in rc)
        elif rc:
            out.append(str(rc))
    return out


def _load_cases() -> list[dict]:
    holdout = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    cases = list(holdout["cases"])
    by_id = {int(c["procurement_id"]): c for c in cases}
    if MODE == "full":
        cal = json.loads(CALIBRATION.read_text(encoding="utf-8"))
        return list(cal["cases"])
    if MODE == "holdout":
        return cases
    cal = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    for c in cal["cases"]:
        pid = int(c["procurement_id"])
        if pid in RESIDUAL_IDS and pid not in by_id:
            cases.append(c)
            by_id[pid] = c
    return cases


def _build_prompt(engine, procurement) -> str:
    registry, _, _ = engine.load_registry()
    priors = engine._load_priors()
    form = classify_procurement_form(procurement)
    return build_v6_1_prompt(
        procurement,
        registry=registry,
        okpd_priors=priors,
        routing_signals=[],
        procurement_form_prior=form.value,
    )


def _enrich_from_db(crm, out: dict) -> dict:
    rid = out.get("inference_run_id")
    if not rid:
        return out
    ir = crm.execute_query(
        """
        SELECT validated_model_result, raw_model_json, prompt_version,
               parse_status, validation_status, raw_model_sha256,
               model_name, model_version
        FROM crm_v3_model_inference_runs WHERE id=%s
        """,
        (rid,),
    )
    if not ir:
        return out
    row = ir[0]
    for k in (
        "validated_model_result",
        "raw_model_json",
        "prompt_version",
        "parse_status",
        "validation_status",
        "raw_model_sha256",
        "model_name",
        "model_version",
    ):
        if row.get(k) is not None:
            out[k] = row.get(k)
    return out


def _score(case, out, allowed: set[str], arm: str, elapsed: float) -> dict:
    val = out.get("validated_model_result")
    if not isinstance(val, dict):
        val = out.get("raw_model_json") if isinstance(out.get("raw_model_json"), dict) else {}
    hyps = _hyps(val)
    cats = _cats(hyps)
    invalid = [c for c in cats if c not in allowed]
    kind = case["expected_label_kind"]
    expect = case.get("expected_exact_category")
    oc = val.get("object_classification") if isinstance(val.get("object_classification"), dict) else {}
    bucket = str(case.get("bucket") or "")
    is_object = "OBJECT" in bucket or kind == "AMBIGUOUS_REVIEW"
    spam = False
    if is_object and cats:
        spam = bool(PRODUCT_SPAM_CODES.intersection(cats))

    row = {
        "arm": arm,
        "procurement_id": case["procurement_id"],
        "bucket": bucket,
        "expected_label_kind": kind,
        "expected_exact_category": expect,
        "EXPECTED_LABEL": expect or kind,
        "prompt_version": out.get("prompt_version") or V61,
        "model_name": out.get("model_name"),
        "inference_run_id": out.get("inference_run_id"),
        "parse_status": out.get("parse_status"),
        "validation_status": out.get("validation_status"),
        "RAW_SHA": out.get("raw_model_sha256"),
        "categories": cats,
        "empty_hypothesis_status": val.get("empty_hypothesis_status") if isinstance(val, dict) else None,
        "invalid_category_codes": invalid,
        "nonempty": bool(cats),
        "object_type": oc.get("object_type"),
        "object_subtype": oc.get("object_subtype"),
        "work_stage": oc.get("work_stage") or oc.get("project_stage"),
        "procurement_form": val.get("procurement_form") if isinstance(val, dict) else None,
        "confidence": _conf(hyps),
        "reason_codes": _reasons(hyps),
        "seconds": round(elapsed, 3),
        "object_spam": spam,
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
        row["exact_match"] = None
        row["missed"] = None
        row["false_positive"] = None
        row["correct_empty"] = None
        row["object_contextual"] = bool(cats) and not spam
    return row


def _agg(rows: list[dict]) -> dict:
    exact = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EXACT_CATEGORY"]
    empties = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EMPTY"]
    objects = [
        r
        for r in rows
        if "OBJECT" in str(r.get("bucket") or "")
        or r.get("expected_label_kind") == "AMBIGUOUS_REVIEW"
    ]
    secs = [float(r["seconds"]) for r in rows if r.get("seconds") is not None]
    form_ok = sum(1 for r in rows if r.get("procurement_form"))
    otype_ok = sum(1 for r in rows if r.get("object_type"))
    return {
        "n": len(rows),
        "DIRECT_TOTAL": len(exact),
        "DIRECT_CORRECT": sum(1 for r in exact if r.get("exact_match")),
        "DIRECT_MISSED": sum(1 for r in exact if r.get("missed")),
        "NEGATIVE_TOTAL": len(empties),
        "NEGATIVE_CORRECT_EMPTY": sum(1 for r in empties if r.get("correct_empty")),
        "NEGATIVE_FALSE_POSITIVE": sum(1 for r in empties if r.get("false_positive")),
        "OBJECT_TOTAL": len(objects),
        "OBJECT_CONTEXTUAL": sum(1 for r in objects if r.get("object_contextual")),
        "OBJECT_CATEGORY_SPAM": sum(1 for r in objects if r.get("object_spam")),
        "INVALID_CATEGORY_CODE": sum(len(r.get("invalid_category_codes") or []) for r in rows),
        "FORMAT_INVALID": sum(1 for r in rows if r.get("validation_status") != "VALIDATED_SUCCESS"),
        "AVG_SECONDS_PER_CASE": round(statistics.mean(secs), 3) if secs else None,
        "P50_SECONDS": round(statistics.median(secs), 3) if secs else None,
        "P95_SECONDS": round(sorted(secs)[max(0, int(len(secs) * 0.95) - 1)], 3) if secs else None,
        "PROCUREMENT_FORM_QUALITY": round(form_ok / max(1, len(rows)), 3),
        "OBJECT_TYPE_QUALITY": round(otype_ok / max(1, len(rows)), 3),
    }


def _run_arm(crm, engine, cases, allowed, model: str | None, arm: str) -> list[dict]:
    rows = []
    for i, case in enumerate(cases, 1):
        pid = int(case["procurement_id"])
        prow = crm.execute_query("SELECT * FROM crm_procurements WHERE id=%s", (pid,))
        if not prow:
            continue
        row = dict(prow[0])
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
                "region": row.get("delivery_region"),
                "customer": row.get("customer"),
                "source_table": row.get("source_table"),
            }
        prompt = _build_prompt(engine, procurement)
        t0 = time.perf_counter()
        out = run_shadow_inference(
            crm,
            procurement_id=pid,
            procurement=procurement,
            model_input=mi if isinstance(mi, dict) else None,
            acquire_gpu=True,
            dry_run_persist=False,
            compute_business_preview=False,
            prompt_version=V61,
            prompt_text=prompt,
            experiment_model=model,
            num_predict=NUM_PREDICT,
            format_json=FORMAT_JSON,
        )
        elapsed = time.perf_counter() - t0
        out = _enrich_from_db(crm, out)
        scored = _score(case, out, allowed, arm, elapsed)
        rows.append(scored)
        print(json.dumps({"i": i, **scored}, ensure_ascii=False), flush=True)
    return rows


def main() -> int:
    cases = _load_cases()
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    _, allowed, _ = engine.load_registry()
    allowed_set = set(allowed)

    a_before = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o_before = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )

    # Fair comparison: same frozen prompt; Qwen baseline then T-lite candidate.
    qwen_rows: list[dict] = []
    t_lite_rows: list[dict] = []
    if ARMS in ("both", "qwen"):
        qwen_rows = _run_arm(crm, engine, cases, allowed_set, None, "qwen_v6_1")
    if ARMS in ("both", "t_lite"):
        t_lite_rows = _run_arm(crm, engine, cases, allowed_set, T_LITE_MODEL, "t_lite_v6_1")

    a_after = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o_after = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )

    q_agg = _agg(qwen_rows)
    t_agg = _agg(t_lite_rows)

    by_q = {int(r["procurement_id"]): r for r in qwen_rows}
    by_t = {int(r["procurement_id"]): r for r in t_lite_rows}
    paired = []
    for c in cases:
        pid = int(c["procurement_id"])
        q = by_q.get(pid, {})
        t = by_t.get(pid, {})
        paired.append(
            {
                "PROCUREMENT_ID": pid,
                "EXPECTED_LABEL": c.get("expected_exact_category") or c.get("expected_label_kind"),
                "QWEN_BASELINE_RESULT": q.get("categories"),
                "T_LITE_RESULT": t.get("categories"),
                "T_LITE_PROCUREMENT_FORM": t.get("procurement_form"),
                "T_LITE_OBJECT_TYPE": t.get("object_type"),
                "T_LITE_OBJECT_SUBTYPE": t.get("object_subtype"),
                "T_LITE_WORK_STAGE": t.get("work_stage"),
                "T_LITE_CATEGORY_HYPOTHESES": t.get("categories"),
                "T_LITE_CONFIDENCE": t.get("confidence"),
                "T_LITE_EMPTY_HYPOTHESIS_STATUS": t.get("empty_hypothesis_status"),
                "T_LITE_REASON_CODES": t.get("reason_codes"),
                "VALIDATION_STATUS": t.get("validation_status"),
                "RAW_SHA": t.get("RAW_SHA"),
            }
        )

    residual = []
    for pid in RESIDUAL_IDS:
        residual.append(
            {
                "PROCUREMENT_ID": pid,
                "QWEN_RESULT": by_q.get(pid, {}).get("categories"),
                "T_LITE_RESULT": by_t.get(pid, {}).get("categories"),
                "QWEN_MISSED": by_q.get(pid, {}).get("missed"),
                "T_LITE_MISSED": by_t.get(pid, {}).get("missed"),
                "QWEN_FP": by_q.get(pid, {}).get("false_positive"),
                "T_LITE_FP": by_t.get(pid, {}).get("false_positive"),
            }
        )

    screening_pass = None
    if MODE == "screening":
        screening_pass = (
            t_agg["INVALID_CATEGORY_CODE"] == 0
            and t_agg["DIRECT_MISSED"] <= q_agg["DIRECT_MISSED"]
            and t_agg["NEGATIVE_FALSE_POSITIVE"] <= q_agg["NEGATIVE_FALSE_POSITIVE"]
            and t_agg["OBJECT_CATEGORY_SPAM"] == 0
        )

    summary = {
        "MODE": MODE,
        "PROMPT_VERSION": V61,
        "NUM_PREDICT": NUM_PREDICT,
        "T_LITE_MODEL_ID": T_LITE_MODEL,
        "QWEN_MODEL": QWEN_MODEL,
        "T_LITE_AND_QWEN_PROMPT_IDENTICAL": "YES",
        "FORMAT_JSON": FORMAT_JSON,
        "DECODING_NOTE": (
            "Qwen uses production /api/generate+format=json; "
            "T-lite experiment_model uses /api/chat+format=json+think=false "
            "(Qwen3 GGUF otherwise spends num_predict on hidden thinking → empty content)"
        ),
        "T_LITE_SCREENING_CASES": len(cases) if MODE == "screening" else None,
        "qwen_v6_1": q_agg,
        "t_lite_v6_1": t_agg,
        "T_LITE_SCREENING": (
            ("PASS" if screening_pass else "FAIL") if screening_pass is not None else None
        ),
        "residual_known_problem_cases": residual,
        "paired_cases": paired,
        "PRODUCTION_ASSESSMENTS_MUTATED": a_after - a_before,
        "PRODUCTION_OPPORTUNITIES_MUTATED": o_after - o_before,
        "results": {"qwen_v6_1": qwen_rows, "t_lite_v6_1": t_lite_rows},
    }
    OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        "SUMMARY="
        + json.dumps({k: summary[k] for k in summary if k not in ("results", "paired_cases")}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
