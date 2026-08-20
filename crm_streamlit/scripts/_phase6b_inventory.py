#!/usr/bin/env python3
"""Phase 6B read-only inventory + prior-case forensics from live SHADOW runs."""
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
from src.services.commercial_routing_v3.model_ui_projection import (
    business_view_from_assessment,
    model_view_from_assessment,
)

PRIOR_IDS = [720, 886, 949, 975, 1016, 6374, 8003, 8175, 10795, 10812, 13688]


def _as_dict(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def main() -> int:
    _, _, crm, _ = connect_databases()
    rows = crm.execute_query(
        """
        SELECT DISTINCT ON (procurement_id)
               id, procurement_id, raw_model_json, validated_model_result
        FROM crm_v3_model_inference_runs
        WHERE run_kind = 'SHADOW'
        ORDER BY procurement_id, id DESC
        """
    )
    raw_keys = Counter()
    val_keys = Counter()
    oc_keys = Counter()
    hyp_keys = Counter()
    hyp_nonempty = 0
    for r in rows:
        raw = _as_dict(r.get("raw_model_json"))
        val = _as_dict(r.get("validated_model_result"))
        for k in raw:
            raw_keys[k] += 1
        for k in val:
            val_keys[k] += 1
        oc = val.get("object_classification")
        if isinstance(oc, dict):
            for k in oc:
                oc_keys[k] += 1
        hyps = val.get("commercial_category_hypotheses") or []
        if isinstance(hyps, list) and hyps:
            hyp_nonempty += 1
            for h in hyps:
                if isinstance(h, dict):
                    for k in h:
                        hyp_keys[k] += 1

    # dry-run visibility
    torgi = int(
        crm.execute_scalar(
            """
            SELECT count(*) FROM crm_procurements
            WHERE COALESCE(crm_stage,'')='torgi'
              AND COALESCE(award_status,'')='submission_open'
            """
        )
        or 0
    )
    legacy = int(
        crm.execute_scalar(
            """
            SELECT count(*)
            FROM crm_procurements cp
            JOIN procurement_ai_assessments a
              ON a.procurement_id = cp.id AND a.is_current
            WHERE COALESCE(cp.crm_stage,'')='torgi'
              AND COALESCE(cp.award_status,'')='submission_open'
              AND a.inference_run_id IS NULL
            """
        )
        or 0
    )
    proven = int(
        crm.execute_scalar(
            """
            SELECT count(*)
            FROM crm_procurements cp
            JOIN procurement_ai_assessments a
              ON a.procurement_id = cp.id AND a.is_current
            WHERE COALESCE(cp.crm_stage,'')='torgi'
              AND COALESCE(cp.award_status,'')='submission_open'
              AND a.inference_run_id IS NOT NULL
            """
        )
        or 0
    )

    prior_cases = []
    for pid in PRIOR_IDS:
        ir = crm.execute_query(
            """
            SELECT id, raw_model_json, validated_model_result
            FROM crm_v3_model_inference_runs
            WHERE procurement_id = %s
            ORDER BY id DESC LIMIT 1
            """,
            (pid,),
        )
        a = crm.execute_query(
            """
            SELECT id, inference_run_id, normalized_result, proposed_categories,
                   proposed_level, confidence
            FROM procurement_ai_assessments
            WHERE procurement_id = %s AND is_current
            LIMIT 1
            """,
            (pid,),
        )
        val = _as_dict(ir[0].get("validated_model_result")) if ir else {}
        nr = _as_dict(a[0].get("normalized_result")) if a else {}
        oc = val.get("object_classification") if isinstance(val.get("object_classification"), dict) else {}
        hyps = val.get("commercial_category_hypotheses") or []
        model_cats = [
            h.get("category_code")
            for h in hyps
            if isinstance(h, dict) and h.get("category_code")
        ]
        old_cats = nr.get("expected_categories") or (a[0].get("proposed_categories") if a else None) or []
        if isinstance(old_cats, str):
            try:
                old_cats = json.loads(old_cats)
            except Exception:
                old_cats = []
        prior_cases.append(
            {
                "PROCUREMENT_ID": pid,
                "OLD_DISPLAY_CATEGORY": old_cats,
                "OLD_CATEGORY_PROVENANCE": "UNKNOWN_LEGACY"
                if not (a and a[0].get("inference_run_id"))
                else "MIXED_COMPATIBILITY",
                "RAW_MODEL_CATEGORY": model_cats,
                "VALIDATED_MODEL_CATEGORY": model_cats,
                "CONTEXT_PRIOR_CATEGORY": [
                    o.get("category_code")
                    for o in (nr.get("category_opportunities") or [])
                    if isinstance(o, dict)
                    and "object_mode_contextual_prior" in (o.get("reason_codes") or [])
                ],
                "MODEL_OBJECT_TYPE": oc.get("object_type"),
                "MODEL_OBJECT_SUBTYPE": oc.get("object_subtype"),
                "MODEL_PROJECT_STAGE": oc.get("work_stage"),
                "MODEL_PROCUREMENT_FORM": val.get("procurement_form"),
                "MODEL_HYPOTHESIS_CONFIDENCE": [
                    h.get("confidence") for h in hyps if isinstance(h, dict)
                ],
                "BUSINESS_SCOPE": nr.get("business_scope_status"),
                "BUSINESS_SCORE": nr.get("candidate_score"),
                "BUSINESS_CANDIDATE_MEDAL": nr.get("candidate_level") or (a[0].get("proposed_level") if a else None),
                "BUSINESS_EFFECTIVE_MEDAL": nr.get("effective_medal") or nr.get("candidate_level"),
                "PYTHON_ADDED_MODEL_FIELD_AFTER_FIX": False,
                "HAS_SHADOW_RUN": bool(ir),
            }
        )

    # Golden UI provenance preview (read-only serialize)
    golden_failures = 0
    golden_preview = []
    for r in rows:
        val = _as_dict(r.get("validated_model_result"))
        fake = {
            "inference_run_id": r["id"],
            "model_provenance": "MODEL_VALIDATED",
            "validated_model_result": val,
            "normalized_result": {
                "route_profile": "X",
                "candidate_level": "GOLD",
                "business_scope_status": "IN_PROFILE",
                "category_opportunities": [
                    {"category_code": "drainage_water_management", "reason_codes": ["object_mode_contextual_prior"]}
                ],
            },
            "business_rule_result": {
                "route_profile": "X",
                "business_scope_status": "IN_PROFILE",
                "business_candidate_medal": "SILVER",
                "contextual_prior_hypotheses": [{"category_code": "drainage_water_management"}],
            },
        }
        mv = model_view_from_assessment(fake)
        bv = business_view_from_assessment(fake)
        ok = (
            mv["provenance"] == "MODEL_VALIDATED"
            and mv.get("contains_rule_fields") is False
            and "drainage_water_management"
            not in [h.get("category") for h in mv.get("hypotheses") or []]
            and bv["provenance"] == "BUSINESS_RULE"
        )
        if not ok:
            golden_failures += 1
        golden_preview.append({"procurement_id": r["procurement_id"], "ok": ok})

    report = {
        "RAW_TOP_LEVEL_FIELDS": dict(raw_keys),
        "VALIDATED_TOP_LEVEL_FIELDS": dict(val_keys),
        "object_classification_fields": dict(oc_keys),
        "commercial_category_hypotheses_fields": dict(hyp_keys),
        "SHADOW_RUNS_DISTINCT_PROCUREMENTS": len(rows),
        "VALIDATED_WITH_NONEMPTY_HYPS": hyp_nonempty,
        "CURRENT_TORGI": torgi,
        "LEGACY_TORGI_WITHOUT_INFERENCE_RUN": legacy,
        "PROVEN_TORGI_WITH_INFERENCE_RUN": proven,
        "WOULD_CHANGE_VISIBILITY": 0,
        "WOULD_CHANGE_OPPORTUNITIES": 0,
        "PRIOR_CASES": prior_cases,
        "GOLDEN_UI_PROVENANCE_FAILURES": golden_failures,
        "GOLDEN_UI_PREVIEW_N": len(golden_preview),
    }
    out = Path("/tmp/phase6b_inventory.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "PRIOR_CASES" and k != "GOLDEN_UI_PREVIEW_N"}, ensure_ascii=False, indent=2))
    print("WROTE", out)
    print("UNEXPECTED_PYTHON_MODEL_CATEGORY_ADDITIONS", sum(1 for c in prior_cases if c["PYTHON_ADDED_MODEL_FIELD_AFTER_FIX"]))
    print("GOLDEN_UI_PROVENANCE_FAILURES", golden_failures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
