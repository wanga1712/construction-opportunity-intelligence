#!/usr/bin/env python3
"""One-case SHADOW smoke: T-lite via experiment_model (/api/chat)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
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

MODEL = "hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M"


def main() -> int:
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    registry, _, _ = engine.load_registry()
    priors = engine._load_priors()
    rows = crm.execute_query("SELECT * FROM crm_procurements WHERE id=%s", (23,))
    row = dict(rows[0])
    mi = ensure_v3_model_input(row, crm)
    procurement = model_input_as_prompt_procurement(mi)
    procurement["v3_model_input"] = mi
    form = classify_procurement_form(procurement)
    prompt = build_v6_1_prompt(
        procurement,
        registry=registry,
        okpd_priors=priors,
        routing_signals=[],
        procurement_form_prior=form.value,
    )
    print("PROMPT_CHARS", len(prompt))
    t0 = time.time()
    out = run_shadow_inference(
        crm,
        procurement_id=23,
        procurement=procurement,
        model_input=mi,
        acquire_gpu=True,
        dry_run_persist=False,
        compute_business_preview=False,
        prompt_version=V61,
        prompt_text=prompt,
        experiment_model=MODEL,
        num_predict=NUM_PREDICT,
        format_json=True,
    )
    sec = round(time.time() - t0, 2)
    rid = out.get("inference_run_id")
    ir = crm.execute_query(
        "SELECT validation_status, raw_model_sha256, validated_model_result, ollama_metadata FROM crm_v3_model_inference_runs WHERE id=%s",
        (rid,),
    )[0]
    val = ir.get("validated_model_result") or {}
    hyps = val.get("commercial_category_hypotheses") if isinstance(val, dict) else None
    meta = ir.get("ollama_metadata") or {}
    print(
        json.dumps(
            {
                "seconds": sec,
                "validation_status": ir.get("validation_status"),
                "raw_sha": ir.get("raw_model_sha256"),
                "categories": [
                    h.get("category_code")
                    for h in (hyps or [])
                    if isinstance(h, dict)
                ],
                "endpoint": meta.get("generation_endpoint") if isinstance(meta, dict) else None,
                "use_chat": meta.get("use_chat") if isinstance(meta, dict) else None,
                "prompt_eval_count": meta.get("prompt_eval_count") if isinstance(meta, dict) else None,
            },
            ensure_ascii=False,
        )
    )
    return 0 if ir.get("validation_status") == "VALIDATED_SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
