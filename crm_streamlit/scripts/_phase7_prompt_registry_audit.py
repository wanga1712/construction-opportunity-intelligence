#!/usr/bin/env python3
"""Phase 7 — reconstruct live prompt path + registry delivery for representative cases."""
from __future__ import annotations

import hashlib
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
from src.services.commercial_routing_v3.prompt import (
    NUM_PREDICT,
    PROMPT_VERSION,
    build_v3_prompt,
    build_v3_prompt_from_model_input,
)

# Representative sets
DIRECTISH = [1, 21782]  # lighting-ish / medical equipment
OBJECTISH = [840, 8003, 13248, 720, 886]
NEGISH = [21782]  # may be outside registry
PRIOR11 = [720, 886, 949, 975, 1016, 6374, 8003, 8175, 10795, 10812, 13688]

# Expand from golden snapshot if present
_GOLDEN = ROOT / "docs" / "reports" / "crm_v3_model_authority_restoration" / "GOLDEN_BAD_CASE_SNAPSHOT.json"


def main() -> int:
    ids = sorted(set(DIRECTISH + OBJECTISH + PRIOR11))
    if _GOLDEN.is_file():
        data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
        # take first 10 + last 5 + priors
        gids = [int(c["procurement_id"]) for c in data["cases"]]
        ids = sorted(set(ids + gids[:10] + gids[20:25] + gids[-5:]))

    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    registry, allowed, _subs = engine.load_registry()
    priors = engine._load_priors()

    registry_empty_prompts = 0
    registry_missing_prompts = 0
    reg_counts = []
    rows_out = []
    uses_model_input = 0
    uses_generic = 0

    for pid in ids:
        prow = crm.execute_query("SELECT * FROM crm_procurements WHERE id=%s", (pid,))
        if not prow:
            rows_out.append({"procurement_id": pid, "error": "NOT_FOUND"})
            continue
        row = dict(prow[0])
        try:
            mi = ensure_v3_model_input(row, crm)
        except Exception as exc:
            mi = None
            mi_err = str(exc)
        else:
            mi_err = None
        procurement = dict(row)
        procurement["title"] = row.get("auction_name") or row.get("title")
        procurement["price"] = float(row.get("initial_price") or 0)
        procurement["region"] = row.get("delivery_region")
        if isinstance(mi, dict):
            procurement["v3_model_input"] = mi
        prompt = engine.build_prompt_context(procurement)
        ph = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        # Which builder?
        via_mi = isinstance(mi, dict) and bool(mi.get("model_input_version"))
        if via_mi:
            uses_model_input += 1
            builder = "build_v3_prompt_from_model_input"
        else:
            uses_generic += 1
            builder = "build_v3_prompt"
        # Registry presence in prompt text
        codes_in_prompt = sum(1 for c in allowed if f"- {c}" in prompt or f"{c}:" in prompt)
        if "ALLOWED_COMMERCIAL_CATEGORY_CODES" not in prompt and "Коммерческие категории" not in prompt:
            registry_missing_prompts += 1
        if codes_in_prompt == 0:
            registry_empty_prompts += 1
        reg_counts.append(codes_in_prompt)
        # OKPD prior / title hints in prompt
        okpd_prior_mentions = prompt.count("okpd_pattern") + prompt.lower().count("prior")
        title_hint = 0
        for code in ("lighting", "waterproofing", "drainage", "computers"):
            if code in prompt:
                title_hint += 1

        # persisted shadow meta if any
        ir = crm.execute_query(
            """
            SELECT id, prompt_hash, prompt_version, length(raw_model_text) AS raw_len,
                   ollama_metadata, raw_model_json
            FROM crm_v3_model_inference_runs
            WHERE procurement_id=%s AND run_kind='SHADOW'
            ORDER BY id DESC LIMIT 1
            """,
            (pid,),
        )
        meta = {}
        raw_hyp = None
        if ir:
            meta = ir[0].get("ollama_metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta)
            rj = ir[0].get("raw_model_json") or {}
            if isinstance(rj, str):
                rj = json.loads(rj)
            hyps = rj.get("commercial_category_hypotheses") if isinstance(rj, dict) else []
            raw_hyp = len(hyps) if isinstance(hyps, list) else 0

        rows_out.append(
            {
                "procurement_id": pid,
                "title": (row.get("auction_name") or "")[:80],
                "PROMPT_VERSION": PROMPT_VERSION,
                "PROMPT_HASH": ph,
                "BUILDER": builder,
                "USES_BUILD_V3_PROMPT_FROM_MODEL_INPUT": via_mi,
                "MODEL_INPUT_VERSION": (mi or {}).get("model_input_version") if isinstance(mi, dict) else None,
                "MODEL_INPUT_ERROR": mi_err,
                "REGISTRY_ACTIVE_CATEGORY_COUNT": len(allowed),
                "REGISTRY_CODES_IN_PROMPT": codes_in_prompt,
                "PROMPT_CHARS": len(prompt),
                "NUM_PREDICT_CONFIG": NUM_PREDICT,
                "OKPD_PRIOR_HINT_SCORE": okpd_prior_mentions,
                "TITLE_HINT_SCORE": title_hint,
                "SHADOW_RAW_HYP_COUNT": raw_hyp,
                "SHADOW_EVAL_COUNT": meta.get("eval_count"),
                "SHADOW_PROMPT_EVAL_COUNT": meta.get("prompt_eval_count"),
                "SHADOW_RETRY": meta.get("model_format_retry_count") or meta.get("attempt_count"),
            }
        )

    summary = {
        "PROMPT_VERSION": PROMPT_VERSION,
        "NUM_PREDICT": NUM_PREDICT,
        "REGISTRY_ACTIVE_TOTAL": len(allowed),
        "REGISTRY_EMPTY_PROMPTS": registry_empty_prompts,
        "REGISTRY_MISSING_PROMPTS": registry_missing_prompts,
        "REGISTRY_ACTIVE_CATEGORY_COUNT_MIN": min(reg_counts) if reg_counts else None,
        "REGISTRY_ACTIVE_CATEGORY_COUNT_MAX": max(reg_counts) if reg_counts else None,
        "USES_BUILD_V3_PROMPT_FROM_MODEL_INPUT_COUNT": uses_model_input,
        "USES_BUILD_V3_PROMPT_GENERIC_COUNT": uses_generic,
        "SAMPLE_ALLOWED_CODES": sorted(list(allowed))[:20],
        "cases": rows_out,
    }
    Path("/tmp/phase7_prompt_registry_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in summary if k != "cases"}, ensure_ascii=False, indent=2))
    print("CASES", len(rows_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
