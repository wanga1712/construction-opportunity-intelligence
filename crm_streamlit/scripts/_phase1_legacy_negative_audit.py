#!/usr/bin/env python3
"""Read-only audit of legacy expert negatives and rejection reasons."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.db_bootstrap import connect_databases


def main() -> None:
    _, _, crm, _ = connect_databases()
    rows = crm.execute_query(
        """
        SELECT id, procurement_id, payload
        FROM crm_v3_expert_annotations
        WHERE is_current = TRUE
        """
    )
    legacy_neg = []
    reason_counts = {
        "NOT_OUR_PRODUCT_OR_WORK": 0,
        "NOT_OUR_OBJECT": 0,
        "NOT_OUR_STAGE": 0,
        "OTHER": 0,
        "MISSING": 0,
    }
    with_category_scope = 0
    out_of_profile = 0
    for row in rows or []:
        payload = row.get("payload") or {}
        if payload.get("expert_category_scope"):
            with_category_scope += 1
        is_neg = (
            payload.get("expert_commercial_verdict") == "NO_COMMERCIAL_ENTRY"
            or payload.get("expert_scope_verdict") == "OUT_OF_PROFILE"
            or payload.get("expert_medal") == "NCE"
            or "OUT_OF_PROFILE" in (payload.get("error_reasons") or [])
        )
        if not is_neg:
            continue
        out_of_profile += 1
        if not payload.get("expert_category_scope"):
            legacy_neg.append(row)
        reasons = []
        for key in ("rejection_reason", "medal_reason"):
            if payload.get(key):
                reasons.append(str(payload.get(key)))
        for err in payload.get("error_reasons") or []:
            reasons.append(str(err))
        for opp in payload.get("rejected_model_opportunities") or []:
            if isinstance(opp, dict) and opp.get("rejection_reason"):
                reasons.append(str(opp["rejection_reason"]))
        joined = " | ".join(reasons).upper()
        if not reasons:
            reason_counts["MISSING"] += 1
        elif "NOT_OUR_PRODUCT" in joined or "PRODUCT_OR_WORK" in joined:
            reason_counts["NOT_OUR_PRODUCT_OR_WORK"] += 1
        elif "NOT_OUR_OBJECT" in joined or "WRONG_OBJECT" in joined or "OBJECT" in joined and "NOT_OUR" in joined:
            reason_counts["NOT_OUR_OBJECT"] += 1
        elif "NOT_OUR_STAGE" in joined or "WRONG_STAGE" in joined:
            reason_counts["NOT_OUR_STAGE"] += 1
        else:
            reason_counts["OTHER"] += 1

    out = {
        "CURRENT_NEGATIVE_STORAGE_SEMANTICS": (
            "OUT_OF_PROFILE shortcut sets expert_scope_verdict=OUT_OF_PROFILE, "
            "expert_commercial_verdict=NO_COMMERCIAL_ENTRY, expert_medal=NCE, "
            "error_reasons=[OUT_OF_PROFILE]; classified as NOT_INTERESTING"
        ),
        "CURRENT_NEGATIVE_FIELDS": [
            "expert_scope_verdict",
            "expert_commercial_verdict",
            "expert_medal",
            "error_reasons",
            "annotation_review_scope",
            "rejection_reason (per opp)",
        ],
        "TOTAL_CURRENT_ANNOTATIONS": len(rows or []),
        "WITH_CATEGORY_SCOPE": with_category_scope,
        "LEGACY_NEGATIVE_TOTAL": len(legacy_neg),
        "OUT_OF_PROFILE_STYLE_TOTAL": out_of_profile,
        "LEGACY_REASON_NOT_OUR_PRODUCT_OR_WORK": reason_counts["NOT_OUR_PRODUCT_OR_WORK"],
        "LEGACY_REASON_NOT_OUR_OBJECT": reason_counts["NOT_OUR_OBJECT"],
        "LEGACY_REASON_NOT_OUR_STAGE": reason_counts["NOT_OUR_STAGE"],
        "LEGACY_REASON_OTHER": reason_counts["OTHER"],
        "LEGACY_REASON_MISSING": reason_counts["MISSING"],
        "sample_legacy_ids": [r["procurement_id"] for r in legacy_neg[:15]],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
