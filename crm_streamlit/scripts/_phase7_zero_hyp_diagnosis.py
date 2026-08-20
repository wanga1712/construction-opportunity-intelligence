#!/usr/bin/env python3
"""Phase 7 — diagnose zero commercial_category_hypotheses from Phase 6A SHADOW runs."""
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


def _d(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def main() -> int:
    _, _, crm, _ = connect_databases()
    # Prefer latest SHADOW per procurement from golden window
    rows = crm.execute_query(
        """
        SELECT DISTINCT ON (procurement_id)
               id, procurement_id, prompt_version, prompt_hash,
               raw_model_text, raw_model_json, validated_model_result,
               ollama_metadata, retry_count, parse_status, validation_status,
               length(raw_model_text) AS raw_len
        FROM crm_v3_model_inference_runs
        WHERE run_kind = 'SHADOW'
        ORDER BY procurement_id, id DESC
        """
    )
    hyp_nonempty = 0
    hyp_empty = 0
    empty_status = Counter()
    forms = Counter()
    obj_type_nonempty = 0
    obj_type_empty = 0
    trunc = 0
    format_retry = 0
    raw_hyp_n = 0
    val_hyp_n = 0
    eval_counts = []
    done_reasons = Counter()

    for r in rows:
        raw = _d(r.get("raw_model_json"))
        val = _d(r.get("validated_model_result"))
        meta = _d(r.get("ollama_metadata"))
        hyps = raw.get("commercial_category_hypotheses")
        if not isinstance(hyps, list):
            hyps = []
        vhyps = val.get("commercial_category_hypotheses")
        if not isinstance(vhyps, list):
            vhyps = []
        if hyps:
            hyp_nonempty += 1
            raw_hyp_n += 1
        else:
            hyp_empty += 1
        if vhyps:
            val_hyp_n += 1
        st = raw.get("empty_hypothesis_status")
        if st is None or st == "":
            empty_status["MISSING"] += 1
        else:
            empty_status[str(st).upper()] += 1
        forms[str(raw.get("procurement_form") or "MISSING").upper()] += 1
        oc = raw.get("object_classification") if isinstance(raw.get("object_classification"), dict) else {}
        if oc.get("object_type"):
            obj_type_nonempty += 1
        else:
            obj_type_empty += 1
        if meta.get("model_format_retry_count") or int(r.get("retry_count") or 0) > 0:
            format_retry += 1
        dr = meta.get("done_reason") or meta.get("stop_reason")
        if dr:
            done_reasons[str(dr)] += 1
        # truncation heuristics
        ev = meta.get("eval_count")
        np = meta.get("num_predict")
        if ev is not None:
            eval_counts.append(int(ev))
            if np is not None and int(ev) >= int(np):
                trunc += 1
        # also check attempt_history
        for att in meta.get("attempt_history") or []:
            if isinstance(att, dict) and str(att.get("status") or "").upper() in (
                "TRUNCATED",
                "LENGTH",
            ):
                trunc += 1

    report = {
        "V5_GOLDEN_RUNS": len(rows),
        "RAW_CATEGORY_HYP_NONEMPTY": hyp_nonempty,
        "RAW_CATEGORY_HYP_EMPTY": hyp_empty,
        "VALIDATED_NONEMPTY_HYPOTHESES": val_hyp_n,
        "RAW_NONEMPTY_HYPOTHESES": raw_hyp_n,
        "VALIDATOR_DROPPED_VALID_HYPOTHESES": max(0, raw_hyp_n - val_hyp_n),
        "EMPTY_STATUS": dict(empty_status),
        "PROCUREMENT_FORM_DISTRIBUTION": dict(forms),
        "OBJECT_TYPE_NONEMPTY": obj_type_nonempty,
        "OBJECT_TYPE_EMPTY": obj_type_empty,
        "TRUNCATED_RUNS_HEURISTIC": trunc,
        "FORMAT_RETRY_RUNS": format_retry,
        "DONE_REASONS": dict(done_reasons),
        "EVAL_COUNT_MIN": min(eval_counts) if eval_counts else None,
        "EVAL_COUNT_MAX": max(eval_counts) if eval_counts else None,
        "EVAL_COUNT_MEDIAN": sorted(eval_counts)[len(eval_counts) // 2] if eval_counts else None,
        "PROMPT_VERSIONS": sorted({r.get("prompt_version") for r in rows}),
    }
    out = Path("/tmp/phase7_zero_hyp_diagnosis.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
