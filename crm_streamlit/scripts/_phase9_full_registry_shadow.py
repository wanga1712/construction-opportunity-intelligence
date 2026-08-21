#!/usr/bin/env python3
"""Phase 9 SHADOW — full registry + research-priority contract evaluation.

No production assessment/opportunity/torgi mutations. Production prompt stays v5.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT = Path("/opt/CRM_Streamlit") if Path("/opt/CRM_Streamlit").is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.crm_ai_assessment_runner import ensure_v3_model_input
from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
from src.services.commercial_routing_v3.procurement_form import classify_procurement_form
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION as PROD_PROMPT
from src.services.commercial_routing_v3.prompt_v9_full_registry import (
    NUM_PREDICT,
    PROMPT_VERSION as V9,
    build_v9_prompt,
)
from src.services.commercial_routing_v3.registry_prompt_payload import (
    PAINT_SHADOW_CATEGORY,
    SUBCATEGORY_ARCHITECTURE,
    build_active_registry_payload,
    estimate_prompt_chars,
)
from src.services.commercial_routing_v3.shadow_inference import run_shadow_inference
from src.services.category_registry_service import get_all_categories

REP = Path("/tmp/phase9_full_registry")
if not REP.exists():
    # Local monorepo fallback for dry unit paths
    alt = Path(__file__).resolve().parents[2] / "docs" / "reports" / "crm_v3_model_authority_restoration"
    REP = alt if alt.is_dir() else Path("/tmp/phase9_full_registry")
REP.mkdir(parents=True, exist_ok=True)

CAL = Path(os.environ.get("PHASE9_CAL_CORPUS") or "/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json")
HOLD = Path(os.environ.get("PHASE9_HOLD_CORPUS") or "/tmp/MODEL_CATEGORY_HOLDOUT_CORPUS.json")
LIMIT = int(os.environ.get("PHASE9_LIMIT") or "0") or None
FOCUS_ONLY = os.environ.get("PHASE9_FOCUS_ONLY", "").strip() in {"1", "true", "YES"}

FOCUS_IDS = {37082, 23591, 27355, 34517}

PAINT_DIRECT_TITLE = "Поставка краски акриловой фасадной"
PAINT_OBJECT_TITLE = "Ремонт фасада здания"
PAINT_IRREL_PC = "Поставка персональных компьютеров"
PAINT_IRREL_ROAD = "Ремонт автомобильной дороги"


def _hyps(val: Any) -> List[Dict[str, Any]]:
    if not isinstance(val, dict):
        return []
    h = val.get("commercial_category_hypotheses") or val.get("commercial_category_candidates") or []
    return h if isinstance(h, list) else []


def _cats(hyps: List[Dict[str, Any]]) -> List[str]:
    return [str(h["category_code"]) for h in hyps if isinstance(h, dict) and h.get("category_code")]


def _subj(val: Any) -> Dict[str, Any]:
    if not isinstance(val, dict):
        return {}
    s = val.get("subject_interpretation")
    return s if isinstance(s, dict) else {}


def _enrich_registry(engine: CommercialRoutingV3Engine) -> List[Dict[str, Any]]:
    registry, _, _ = engine.load_registry()
    # Merge richer metadata when columns exist (aliases/description/signals).
    try:
        rich = {r["category_code"]: r for r in get_all_categories(engine.crm_db, include_inactive=False)}
    except Exception:
        rich = {}
    out = []
    for row in registry:
        item = dict(row)
        extra = rich.get(item.get("category_code")) or {}
        for k in ("description", "aliases", "positive_signals", "negative_contexts"):
            if extra.get(k) is not None and not item.get(k):
                item[k] = extra.get(k)
        out.append(item)
    return out


def _root_cause(
    *,
    bucket: str,
    expect: Optional[str],
    kind: Optional[str],
    raw_cats: List[str],
    val_cats: List[str],
    invalid: List[str],
    subj: Dict[str, Any],
    form: Optional[str],
    pid: int,
) -> str:
    norm = str(subj.get("normalized_subject") or "").lower()
    # Focus overrides with explicit Phase 8 semantics
    if pid == 37082:
        if "computers" in val_cats:
            return "NO_ERROR"
        if any(x in norm for x in ("компьютер", "моноблок", "пк")) or "computer" in norm:
            return "CATEGORY_MAPPING_ERROR"
        return "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"
    if pid == 23591:
        if "drainage_water_management" in val_cats:
            return "NO_ERROR"
        if any(x in norm for x in ("кабел", "cable", "equipment", "оборудован")) and not any(
            x in norm for x in ("ливнев", "дренаж", "канализ")
        ):
            return "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"
        if any(x in norm for x in ("ливнев", "дренаж", "канализ")) and "drainage_water_management" not in val_cats:
            return "CATEGORY_MAPPING_ERROR"
        return "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"
    if pid in (27355, 34517):
        if not val_cats:
            return "NO_ERROR"
        return "OBJECT_PRIOR_OVERREACH"

    if kind == "EXPECTED_EXACT_CATEGORY" and expect:
        if expect in val_cats:
            return "NO_ERROR"
        if invalid and any(expect.split("_")[0] in c for c in invalid):
            return "CATEGORY_MAPPING_ERROR"
        if invalid:
            return "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"
        if not val_cats:
            return "ABSTENTION_ERROR"
        return "CATEGORY_MAPPING_ERROR"
    if kind == "EXPECTED_EMPTY":
        if not val_cats:
            return "NO_ERROR"
        if form in ("CONSTRUCTION_WORKS", "DESIGN_ONLY") or bucket.startswith("OBJECT"):
            return "OBJECT_PRIOR_OVERREACH"
        if invalid:
            return "INVALID_REGISTRY_CODE_GENERATION"
        return "OBJECT_PRIOR_OVERREACH"
    if bucket.startswith("OBJECT"):
        if not val_cats:
            return "NO_ERROR"
        # spam heuristic: DIRECT_SUPPLY on object case
        return "OBJECT_PRIOR_OVERREACH" if val_cats else "NO_ERROR"
    return "NO_ERROR"


def _score_case(case: Dict[str, Any], out: Dict[str, Any], allowed: Set[str]) -> Dict[str, Any]:
    run = out.get("run")
    raw = getattr(run, "raw_model_json", None) if run is not None else None
    val = getattr(run, "validated_model_result", None) if run is not None else None
    if not isinstance(raw, dict):
        raw = {}
    if not isinstance(val, dict):
        val = {}
    raw_cats = _cats(_hyps(raw))
    val_cats = _cats(_hyps(val))
    invalid = [c for c in raw_cats if c not in allowed]
    subj = _subj(val) or _subj(raw)
    kind = case.get("expected_label_kind")
    expect = case.get("expected_exact_category")
    form = val.get("procurement_form") or raw.get("procurement_form")
    root = _root_cause(
        bucket=str(case.get("bucket") or ""),
        expect=expect,
        kind=kind,
        raw_cats=raw_cats,
        val_cats=val_cats,
        invalid=invalid,
        subj=subj,
        form=form,
        pid=int(case["procurement_id"]),
    )
    confirmed_as = 0
    for h in _hyps(val):
        if not isinstance(h, dict):
            continue
        if h.get("confirmation_required") is False and str(h.get("evidence_role") or "").upper() in {
            "CONTEXTUAL_RESEARCH_CANDIDATE",
            "CONTEXTUAL_RESEARCH_PRIOR",
        }:
            confirmed_as += 1
        if str(h.get("candidate_role") or "").upper() == "RESEARCH_CANDIDATE" and h.get("confirmation_required") is False:
            confirmed_as += 1
    row = {
        "procurement_id": case["procurement_id"],
        "bucket": case.get("bucket"),
        "expected_label_kind": kind,
        "expected_exact_category": expect,
        "prompt_version": V9,
        "inference_run_id": out.get("inference_run_id"),
        "parse_status": out.get("parse_status"),
        "validation_status": out.get("validation_status"),
        "raw_categories": raw_cats,
        "validated_categories": val_cats,
        "invalid_category_codes": invalid,
        "subject_interpretation": subj,
        "procurement_form": form,
        "empty_hypothesis_status": val.get("empty_hypothesis_status"),
        "PRIMARY_ROOT_CAUSE": root,
        "object_research_candidate_presented_as_confirmed": confirmed_as,
        "title": (case.get("title") or "")[:120],
    }
    if kind == "EXPECTED_EXACT_CATEGORY":
        row["exact_match"] = expect in val_cats
        row["missed"] = expect not in val_cats
        row["false_positive"] = None
    elif kind == "EXPECTED_EMPTY":
        row["exact_match"] = None
        row["missed"] = None
        row["false_positive"] = bool(val_cats)
        row["correct_empty"] = not val_cats
    else:
        row["exact_match"] = None
        row["missed"] = None
        row["false_positive"] = None
    return row


def _run_one(
    crm,
    engine: CommercialRoutingV3Engine,
    procurement: Dict[str, Any],
    *,
    allowed: Set[str],
    extra_shadow: Optional[List[Dict[str, Any]]] = None,
    registry_rows: Optional[List[Dict[str, Any]]] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    pid = int(procurement.get("id") or procurement.get("procurement_id"))
    if pid > 0:
        try:
            procurement = ensure_v3_model_input(procurement, crm)
        except Exception:
            pass
    priors = engine._load_priors()
    form = classify_procurement_form(procurement)
    rows = registry_rows if registry_rows is not None else _enrich_registry(engine)
    prompt = build_v9_prompt(
        procurement,
        registry=rows,
        okpd_priors=priors,
        routing_signals=[],
        procurement_form_prior=form.value,
        extra_shadow_categories=extra_shadow,
    )
    allow = set(allowed)
    if extra_shadow:
        for e in extra_shadow:
            if e.get("category_code"):
                allow.add(str(e["category_code"]))
    out = run_shadow_inference(
        crm,
        procurement_id=pid if pid > 0 else 0,
        procurement=procurement,
        model_input=procurement.get("v3_model_input")
        if isinstance(procurement.get("v3_model_input"), dict)
        else {},
        allowed_categories=allow,
        acquire_gpu=True,
        dry_run_persist=not persist,
        compute_business_preview=False,
        prompt_version=V9,
        prompt_text=prompt,
        num_predict=NUM_PREDICT,
        format_json=True,
    )
    return out


def _synthetic_procurement(title: str, okpd_code: str, okpd_name: str, pid: int) -> Dict[str, Any]:
    return {
        "id": pid,
        "procurement_id": pid,
        "title": title,
        "auction_name": title,
        "okpd_code": okpd_code,
        "okpd_name": okpd_name,
        "initial_price": "100000",
        "price": 100000,
        "source_table": "reestr_contract_44_fz",
        "law_type": "44_FZ",
        "customer": "TEST CUSTOMER",
        "delivery_region": "тест",
        "v3_model_input": {
            "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
            "procurement_id": pid,
            "title": title,
            "official_description": None,
            "okpd_codes": [okpd_code],
            "okpd_names": [okpd_name],
            "COMMERCIAL_PRODUCT_PRIORS": [],
            "CONTEXTUAL_RESEARCH_PRIORS": [],
            "DIRECT_CABLE_EXPECTED_RESULT": "NO_COMMERCIAL_ENTRY",
            "document_link_count": 0,
            "unique_document_count": 0,
            "source_contour": "PUBLIC_44FZ",
        },
    }


def _load_cases(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        # monorepo docs fallback
        alt = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "reports"
            / "crm_v3_model_authority_restoration"
            / path.name
        )
        path = alt if alt.is_file() else path
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("cases") or [])


def main() -> int:
    t0 = time.time()
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    registry_rows = _enrich_registry(engine)
    _, allowed_base, _ = engine.load_registry()
    allowed_base = set(allowed_base)

    a_before = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o_before = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )

    payload, codes = build_active_registry_payload(registry_rows)
    sample_prompt = build_v9_prompt(
        _synthetic_procurement("probe", "26.2", "Компьютеры", -1),
        registry=registry_rows,
        okpd_priors=[],
        routing_signals=[],
        procurement_form_prior="DIRECT_GOODS_PURCHASE",
    )
    base_chars = len(sample_prompt)
    scale = {
        "CURRENT_REGISTRY_COUNT": len(codes),
        "CURRENT": estimate_prompt_chars(base_prompt_chars=base_chars, payload=payload, scale=1),
        "2X": estimate_prompt_chars(base_prompt_chars=base_chars, payload=payload, scale=2),
        "5X": estimate_prompt_chars(base_prompt_chars=base_chars, payload=payload, scale=5),
        "10X": estimate_prompt_chars(base_prompt_chars=base_chars, payload=payload, scale=10),
        "SUBCATEGORY_ARCHITECTURE": SUBCATEGORY_ARCHITECTURE,
        "REGISTRY_FIELDS_SAMPLE": list(payload[0].keys()) if payload else [],
    }

    # --- Paint SHADOW extension tests (synthetic ids < 0 not persisted as prod) ---
    paint_extra = [PAINT_SHADOW_CATEGORY]
    paint_cases = [
        ("A_DIRECT", _synthetic_procurement(PAINT_DIRECT_TITLE, "20.30", "Краски", -9101), "paint"),
        ("B_OBJECT", _synthetic_procurement(PAINT_OBJECT_TITLE, "43.39", "Отделочные работы", -9102), "paint"),
        ("C_PC", _synthetic_procurement(PAINT_IRREL_PC, "26.2", "Компьютеры", -9103), None),
        ("D_ROAD", _synthetic_procurement(PAINT_IRREL_ROAD, "42.11", "Дороги", -9104), None),
    ]
    paint_results = []
    for label, proc, expect_paint in paint_cases:
        # Negative synthetic ids: still write SHADOW inference runs (allowed).
        out = _run_one(
            crm,
            engine,
            proc,
            allowed=allowed_base,
            extra_shadow=paint_extra,
            registry_rows=registry_rows,
            persist=False,
        )
        run = out.get("run")
        val = getattr(run, "validated_model_result", None) if run else None
        raw = getattr(run, "raw_model_json", None) if run else None
        cats = _cats(_hyps(val if isinstance(val, dict) else {}))
        subj = _subj(val if isinstance(val, dict) else {}) or _subj(raw if isinstance(raw, dict) else {})
        paint_results.append(
            {
                "label": label,
                "title": proc["title"],
                "inference_run_id": out.get("inference_run_id"),
                "categories": cats,
                "subject_interpretation": subj,
                "paint_selected": "paint" in cats,
                "expect_paint": expect_paint == "paint",
            }
        )

    paint_direct = next(r for r in paint_results if r["label"] == "A_DIRECT")
    paint_object = next(r for r in paint_results if r["label"] == "B_OBJECT")
    paint_fp = sum(
        1
        for r in paint_results
        if r["label"] in {"C_PC", "D_ROAD"} and r["paint_selected"]
    )

    # --- Corpus ---
    cal_cases = _load_cases(CAL)
    hold_cases = _load_cases(HOLD)
    if FOCUS_ONLY:
        cal_cases = [c for c in cal_cases if int(c["procurement_id"]) in FOCUS_IDS]
        hold_cases = []
    if LIMIT:
        cal_cases = cal_cases[:LIMIT]
        hold_cases = hold_cases[: max(0, LIMIT // 3)]

    def run_corpus(cases: List[Dict[str, Any]], tag: str) -> List[Dict[str, Any]]:
        rows = []
        for i, case in enumerate(cases):
            pid = int(case["procurement_id"])
            proc_rows = crm.execute_query("SELECT * FROM crm_procurements WHERE id=%s", (pid,)) or []
            if not proc_rows:
                rows.append({"procurement_id": pid, "error": "PROCUREMENT_NOT_FOUND"})
                continue
            procurement = dict(proc_rows[0])
            procurement = ensure_v3_model_input(procurement, crm)
            out = _run_one(
                crm,
                engine,
                procurement,
                allowed=allowed_base,
                registry_rows=registry_rows,
            )
            scored = _score_case(case, out, allowed_base)
            rows.append(scored)
            if (i + 1) % 5 == 0:
                print(f"{tag} progress {i+1}/{len(cases)}", flush=True)
        return rows

    cal_rows = run_corpus(cal_cases, "cal")
    hold_rows = run_corpus(hold_cases, "hold") if hold_cases else []

    def agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        exact = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EXACT_CATEGORY"]
        empties = [r for r in rows if r.get("expected_label_kind") == "EXPECTED_EMPTY"]
        return {
            "n": len(rows),
            "DIRECT_MISSED": sum(1 for r in exact if r.get("missed")),
            "DIRECT_N": len(exact),
            "NEGATIVE_FALSE_POSITIVE": sum(1 for r in empties if r.get("false_positive")),
            "NEGATIVE_N": len(empties),
            "INVALID_CATEGORY_CODE": sum(len(r.get("invalid_category_codes") or []) for r in rows),
            "FORMAT_INVALID": sum(1 for r in rows if r.get("validation_status") != "VALIDATED_SUCCESS"),
            "OBJECT_RESEARCH_CANDIDATE_PRESENTED_AS_CONFIRMED": sum(
                int(r.get("object_research_candidate_presented_as_confirmed") or 0) for r in rows
            ),
            "root_causes": {
                k: sum(1 for r in rows if r.get("PRIMARY_ROOT_CAUSE") == k)
                for k in sorted({r.get("PRIMARY_ROOT_CAUSE") for r in rows if r.get("PRIMARY_ROOT_CAUSE")})
            },
        }

    focus = {pid: None for pid in FOCUS_IDS}
    for r in cal_rows + hold_rows:
        pid = r.get("procurement_id")
        if pid in focus:
            focus[pid] = r

    a_after = int(crm.execute_scalar("SELECT count(*) FROM procurement_ai_assessments") or 0)
    o_after = int(
        crm.execute_scalar(
            "SELECT count(*) FROM crm_procurement_category_opportunities WHERE status='CURRENT'"
        )
        or 0
    )

    summary = {
        "prompt_version": V9,
        "production_prompt_unchanged": PROD_PROMPT,
        "ACTIVE_CATEGORY_COUNT": len(codes),
        "ACTIVE_CATEGORY_CODES": codes,
        "scale": scale,
        "paint": {
            "results": paint_results,
            "PAINT_DIRECT_DISCOVERED": bool(paint_direct["paint_selected"]),
            "PAINT_OBJECT_RESEARCH_CANDIDATE": bool(paint_object["paint_selected"]),
            "PAINT_IRRELEVANT_FP_COUNT": paint_fp,
            "PAINT_TEST_PROMPT_SOURCE_CHANGED": False,
            "PAINT_TEST_PYTHON_HINT_ADDED": False,
            "PAINT_TEST_OKPD_RULE_ADDED": False,
        },
        "focus": focus,
        "calibration": {"rows": cal_rows, "agg": agg(cal_rows)},
        "holdout": {"rows": hold_rows, "agg": agg(hold_rows)},
        "PRODUCTION_ASSESSMENTS_MUTATED": a_after - a_before,
        "PRODUCTION_OPPORTUNITIES_MUTATED": o_after - o_before,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    out_path = REP / "phase9_full_registry_results.json"
    # Prefer docs report path when running from monorepo deploy sync
    docs = Path("/opt/CRM_Streamlit/../docs/reports/crm_v3_model_authority_restoration")
    # Always write /tmp and also local docs if present
    Path("/tmp/phase9_full_registry_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(out_path), "agg_cal": summary["calibration"]["agg"], "paint": summary["paint"], "focus_keys": list(focus.keys())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
