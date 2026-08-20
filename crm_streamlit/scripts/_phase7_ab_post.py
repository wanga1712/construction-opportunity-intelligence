#!/usr/bin/env python3
"""Phase 7 post-AB: road cases + prior11 diagnostic compare + object-class quality."""
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
from src.services.db_bootstrap import connect_databases

PRIOR11 = [720, 886, 949, 975, 1016, 6374, 8003, 8175, 10795, 10812, 13688]
AB = Path("/tmp/phase7_ab_summary.json")
CORPUS = Path("/tmp/MODEL_CATEGORY_CALIBRATION_CORPUS.json")


def _d(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def main() -> int:
    ab = json.loads(AB.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    _, _, crm, _ = connect_databases()

    # Old python categories from opportunities / assessments if present
    prior_rows = []
    for pid in PRIOR11:
        old = crm.execute_query(
            """
            SELECT category_code
            FROM crm_procurement_category_opportunities
            WHERE procurement_id=%s AND status='CURRENT'
            ORDER BY id DESC LIMIT 3
            """,
            (pid,),
        )
        old_cats = [r["category_code"] for r in (old or [])]
        # business priors from latest assessment details if any
        prior_hint = crm.execute_query(
            """
            SELECT details
            FROM procurement_ai_assessments
            WHERE procurement_id=%s
            ORDER BY id DESC LIMIT 1
            """,
            (pid,),
        )
        details = _d(prior_hint[0]["details"]) if prior_hint else {}
        biz = details.get("business_category_hypotheses") or details.get(
            "contextual_prior_hypotheses"
        ) or []
        prior_cat = None
        if isinstance(biz, list) and biz:
            prior_cat = biz[0].get("category_code") if isinstance(biz[0], dict) else None

        def cats_for(arm):
            for r in ab["results"].get(arm, []):
                if int(r["procurement_id"]) == pid:
                    return r.get("categories") or [], r.get("empty_hypothesis_status"), r
            return [], None, None

        v5c, v5e, v5r = cats_for("v5")
        v6c, v6e, v6r = cats_for("v6")
        prior_rows.append(
            {
                "PROCUREMENT_ID": pid,
                "OLD_PYTHON_CATEGORY": old_cats[0] if old_cats else None,
                "OLD_PYTHON_CATEGORIES": old_cats,
                "PRIOR_CATEGORY": prior_cat,
                "V5_MODEL_CATEGORY": v5c,
                "NEW_MODEL_CATEGORY": v6c,
                "MATCH_MODEL_TO_PRIOR": bool(prior_cat and prior_cat in (v6c or [])),
                "V5_EMPTY_STATUS": v5e,
                "V6_EMPTY_STATUS": v6e,
                "MODEL_REASON": "diagnostic_only; OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH=NO",
            }
        )

    road = []
    for case in corpus["cases"]:
        if case["bucket"] not in ("ROAD_CASE_REVIEW", "OBJECT_CONSTRUCTION"):
            continue
        title = (case.get("title") or "").lower()
        if not any(
            k in title
            for k in (
                "дорог",
                "мост",
                "тротуар",
                "спортив",
                "путепровод",
                "слой",
            )
        ):
            continue
        entry = {
            "procurement_id": case["procurement_id"],
            "title": case.get("title"),
            "label_note": case.get("label_note"),
            "arms": {},
        }
        for arm in ("v5", "v6"):
            hit = next(
                (r for r in ab["results"][arm] if r["procurement_id"] == case["procurement_id"]),
                None,
            )
            if not hit:
                continue
            # fetch reason from validated
            reason = None
            conf = None
            if hit.get("inference_run_id"):
                ir = crm.execute_query(
                    "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id=%s",
                    (hit["inference_run_id"],),
                )
                val = _d(ir[0]["validated_model_result"]) if ir else {}
                hyps = val.get("commercial_category_hypotheses") or []
                if hyps and isinstance(hyps[0], dict):
                    reason = hyps[0].get("reason_codes") or hyps[0].get("why_category")
                    conf = hyps[0].get("confidence")
                entry["arms"][arm] = {
                    "OBJECT_TYPE": hit.get("object_type"),
                    "MODEL_CATEGORY_HYPOTHESES": hit.get("categories"),
                    "MODEL_CONFIDENCE": conf,
                    "MODEL_REASON": reason,
                    "empty_hypothesis_status": hit.get("empty_hypothesis_status"),
                    "procurement_form": hit.get("procurement_form"),
                }
        if entry["arms"]:
            road.append(entry)

    # Object classification quality on calibration
    def obj_stats(arm):
        rows = ab["results"][arm]
        forms = sum(1 for r in rows if r.get("procurement_form") and r["procurement_form"] != "UNKNOWN")
        types = sum(1 for r in rows if r.get("object_type"))
        return {
            "OBJECT_TYPE_NONEMPTY": types,
            "PROCUREMENT_FORM_NONEMPTY_NON_UNKNOWN": forms,
            "n": len(rows),
        }

    out = {
        "prior11_diagnostic": prior_rows,
        "road_cases_manual_review": road,
        "object_classification_quality": {"v5": obj_stats("v5"), "v6": obj_stats("v6")},
        "ab_summary_metrics": {k: ab[k] for k in ab if k != "results"},
    }
    Path("/tmp/phase7_ab_post.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
