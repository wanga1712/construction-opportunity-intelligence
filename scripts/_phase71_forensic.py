#!/usr/bin/env python3
"""Phase 7.1 — forensic trace of residual v6_1 failures (SHADOW metadata only)."""
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
from src.services.commercial_routing_v3.prompt import (
    _matched_prior_categories,
    _title_hint_categories,
    build_v3_prompt_from_model_input,
)
from src.services.commercial_routing_v3.prompt_v6 import (
    PROMPT_VERSION as V61,
    build_v6_prompt_from_model_input,
)

FAIL_IDS = [37082, 23591, 27355, 34517]


def _d(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def main() -> int:
    _, _, crm, _ = connect_databases()
    engine = CommercialRoutingV3Engine(crm_db=crm)
    registry, allowed, _ = engine.load_registry()
    priors = engine._load_priors()
    out = []

    for pid in FAIL_IDS:
        rows = crm.execute_query("SELECT * FROM crm_procurements WHERE id=%s", (pid,))
        if not rows:
            out.append({"PROCUREMENT_ID": pid, "error": "NOT_FOUND"})
            continue
        row = dict(rows[0])
        try:
            mi = ensure_v3_model_input(row, crm)
        except Exception as exc:
            mi = None
            mi_err = str(exc)
        else:
            mi_err = None
        procurement = model_input_as_prompt_procurement(mi) if isinstance(mi, dict) else {
            "title": row.get("auction_name"),
            "okpd_code": row.get("okpd_code"),
            "okpd_name": row.get("okpd_name"),
            "price": float(row.get("initial_price") or 0),
        }
        if isinstance(mi, dict):
            procurement["v3_model_input"] = mi
        form_prior = classify_procurement_form(procurement).value
        prompt = build_v6_prompt_from_model_input(
            mi if isinstance(mi, dict) else {
                "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
                "title": procurement.get("title"),
                "okpd_codes": [procurement.get("okpd_code")] if procurement.get("okpd_code") else [],
                "okpd_name": procurement.get("okpd_name"),
            },
            registry=registry,
            okpd_priors=priors,
            procurement_form_prior=form_prior,
        )
        # latest v6_1 SHADOW run
        ir = crm.execute_query(
            """
            SELECT id, prompt_version, raw_model_json, validated_model_result,
                   raw_model_text, parse_status, validation_status
            FROM crm_v3_model_inference_runs
            WHERE procurement_id=%s AND run_kind='SHADOW'
              AND prompt_version LIKE 'v3_category_centric_routing_7b_v6%%'
            ORDER BY id DESC LIMIT 1
            """,
            (pid,),
        )
        raw = _d(ir[0]["raw_model_json"]) if ir else {}
        val = _d(ir[0]["validated_model_result"]) if ir else {}
        hyps = val.get("commercial_category_hypotheses") or raw.get("commercial_category_hypotheses") or []
        oc = val.get("object_classification") or raw.get("object_classification") or {}

        title_hints = _title_hint_categories(procurement)
        okpd_prior_cats = _matched_prior_categories(procurement, priors)

        # Label revalidation hints
        title = (row.get("auction_name") or "").lower()
        label_notes = []
        if pid == 23591:
            # storm sewer equipment supply vs works
            if "поставк" in title and "оборудован" in title:
                label_notes.append("title is SUPPLY of storm-sewer EQUIPMENT — direct goods plausible")
            if "работ" in title or "монтаж" in title or "строительств" in title:
                label_notes.append("title contains works verbs — may be object/works")
            # OKPD 22.23.13.194 tubes/pipes plastic — drainage-adjacent but not named "дренаж"
            label_notes.append(
                "OKPD is plastic tubes/pipes >300mm — maps to drainage family only if commercial "
                "category covers storm-sewer equipment; title says ливневой канализации equipment"
            )

        entry = {
            "PROCUREMENT_ID": pid,
            "TITLE": row.get("auction_name"),
            "OKPD_CODE": row.get("okpd_code"),
            "OKPD_NAME": row.get("okpd_name"),
            "MODEL_INPUT": mi,
            "MODEL_INPUT_ERROR": mi_err,
            "PROCUREMENT_FORM_PRIOR": form_prior,
            "MODEL_PROCUREMENT_FORM": val.get("procurement_form") or raw.get("procurement_form"),
            "REGISTRY_CODES_VISIBLE_TO_MODEL": sorted(list(allowed)),
            "OKPD_PRIORS_VISIBLE_TO_MODEL": okpd_prior_cats,
            "TITLE_HINTS_VISIBLE_TO_MODEL": title_hints,
            "PROMPT_VERSION_REBUILT": V61,
            "PROMPT_CHARS": len(prompt),
            "INFERENCE_RUN_ID": ir[0]["id"] if ir else None,
            "RAW_RESPONSE": raw,
            "VALIDATED_RESPONSE": val,
            "CATEGORY_HYPOTHESES": hyps,
            "EMPTY_HYPOTHESIS_STATUS": val.get("empty_hypothesis_status")
            if val
            else raw.get("empty_hypothesis_status"),
            "REASON_CODES": [
                h.get("reason_codes") for h in hyps if isinstance(h, dict)
            ],
            "CONFIDENCE": [h.get("confidence") for h in hyps if isinstance(h, dict)],
            "OBJECT_CLASSIFICATION": oc,
            "LABEL_REVALIDATION_NOTES": label_notes,
        }
        out.append(entry)

    Path("/tmp/phase71_forensic.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps([{k: e.get(k) for k in (
        "PROCUREMENT_ID","TITLE","OKPD_CODE","OKPD_NAME","PROCUREMENT_FORM_PRIOR",
        "MODEL_PROCUREMENT_FORM","OKPD_PRIORS_VISIBLE_TO_MODEL","TITLE_HINTS_VISIBLE_TO_MODEL",
        "EMPTY_HYPOTHESIS_STATUS","CATEGORY_HYPOTHESES","OBJECT_CLASSIFICATION",
        "LABEL_REVALIDATION_NOTES","INFERENCE_RUN_ID",
    ) if k in e} for e in out], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
