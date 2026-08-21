#!/usr/bin/env python3
"""Phase 8 read-only dump of immutable inference runs (audit only)."""
from __future__ import annotations

import json
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Phase 7 A/B v6_1 (34) + Phase 7.1 ABC v6_1 object/focus re-runs for corpus coverage.
RUN_IDS = sorted(
    {
        # phase7_ab_v61
        219, 221, 223, 225, 227, 229, 231, 233, 235, 237, 239, 241, 243, 245, 247, 249,
        251, 253, 255, 257, 259, 261, 263, 265, 267, 269, 271, 273, 275, 277, 279, 281,
        283, 285,
        # phase71_abc v6_1 selected directs/negs/objects (incl focus re-runs)
        287, 290, 293, 296, 299, 302, 305, 308, 317, 335, 338, 341, 344, 347, 350, 353,
        356, 359, 362, 365, 383, 386, 389, 392, 395, 398, 401, 404, 407, 476,
    }
)
FOCUS = [37082, 23591, 27355, 34517]


def load_env(path: str) -> dict:
    vals = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def main() -> None:
    vals = load_env("/opt/CRM_Streamlit/.env")
    conn = psycopg2.connect(
        host=vals.get("CRM_DB_HOST", "127.0.0.1"),
        port=int(vals.get("CRM_DB_PORT", "5432")),
        dbname=vals.get("CRM_DB_NAME", "crm"),
        user=vals.get("CRM_DB_USER", "crm_app"),
        password=(
            vals.get("CRM_DB_PASSWORD")
            or vals.get("POSTGRES_PASSWORD")
            or vals.get("DB_PASSWORD")
        ),
    )
    out: dict = {"runs": [], "assessments": [], "active_registry": [], "focus_cards": []}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, procurement_id, run_kind, model_name, model_version, prompt_version,
                   prompt_hash, schema_version, parse_status, validation_status,
                   validation_errors, raw_model_json, validated_model_result,
                   raw_model_sha256, validated_model_sha256, created_at
            FROM crm_v3_model_inference_runs
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (RUN_IDS,),
        )
        out["runs"] = [dict(r) for r in cur.fetchall()]
        pids = sorted({int(r["procurement_id"]) for r in out["runs"]})
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='procurement_ai_assessments'
            ORDER BY ordinal_position
            """
        )
        cols = [r["column_name"] for r in cur.fetchall()]
        wanted = [
            c
            for c in [
                "procurement_id",
                "inference_run_id",
                "ai_assessment_status",
                "procurement_form",
                "overall_research_action",
                "candidate_medal",
                "candidate_score",
                "business_rule_result",
                "field_provenance",
                "validated_model_result",
                "model_raw_result",
                "commercial_category_hypotheses",
                "contextual_prior_hypotheses",
                "business_category_hypotheses",
            ]
            if c in cols
        ]
        cur.execute(
            f"SELECT {', '.join(wanted)} FROM procurement_ai_assessments WHERE procurement_id = ANY(%s)",
            (pids,),
        )
        out["assessments"] = [dict(r) for r in cur.fetchall()]
        out["assessment_columns_present"] = wanted
        cur.execute(
            """
            SELECT category_code, category_name, is_active
            FROM crm_product_categories
            WHERE is_active = TRUE
            ORDER BY category_code
            """
        )
        out["active_registry"] = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='procurements'
            ORDER BY ordinal_position
            """
        )
        pcols = {r["column_name"] for r in cur.fetchall()}
        focus_wanted = [
            c
            for c in [
                "id",
                "auction_name",
                "okpd_code",
                "okpd_name",
                "initial_price",
                "customer",
                "delivery_region",
                "source_table",
                "contract_number",
                "crm_stage",
                "tender_link",
            ]
            if c in pcols
        ]
        if focus_wanted:
            cur.execute(
                f"SELECT {', '.join(focus_wanted)} FROM procurements WHERE id = ANY(%s)",
                (FOCUS,),
            )
            out["focus_cards"] = [dict(r) for r in cur.fetchall()]
        else:
            out["focus_cards"] = []
            out["focus_cards_error"] = "procurements columns unavailable"
    Path("/tmp/phase8_immutable_dump.json").write_text(
        json.dumps(out, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    registry = {r["category_code"] for r in out["active_registry"]}
    summary = []
    for r in out["runs"]:
        raw = r.get("raw_model_json") or {}
        val = r.get("validated_model_result") or {}
        raw_cats = [
            h.get("category_code")
            for h in (raw.get("commercial_category_hypotheses") or [])
            if isinstance(h, dict)
        ]
        val_cats = [
            h.get("category_code")
            for h in (val.get("commercial_category_hypotheses") or [])
            if isinstance(h, dict)
        ]
        invalid = [c for c in raw_cats if c and c not in registry]
        oc = raw.get("object_classification") or {}
        summary.append(
            {
                "inference_run_id": r["id"],
                "procurement_id": r["procurement_id"],
                "prompt_version": r["prompt_version"],
                "run_kind": r["run_kind"],
                "raw_cats": raw_cats,
                "val_cats": val_cats,
                "invalid_raw_cats": invalid,
                "raw_form": raw.get("procurement_form"),
                "val_form": val.get("procurement_form"),
                "object_type": oc.get("object_type"),
                "object_subtype": oc.get("object_subtype"),
                "work_stage": oc.get("work_stage"),
                "empty_raw": raw.get("empty_hypothesis_status"),
                "empty_val": val.get("empty_hypothesis_status"),
                "validator_removed": bool(raw_cats) and not val_cats,
            }
        )
    print(json.dumps({"summary": summary, "registry": sorted(registry)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
