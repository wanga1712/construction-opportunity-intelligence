#!/usr/bin/env python3
"""Phase 8 — build decision-trace audit artifacts (local, audit-only)."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REP = ROOT / "docs" / "reports" / "crm_v3_model_authority_restoration"
CRM = ROOT / "crm_streamlit"


def load(name: str):
    text = (REP / name).read_text(encoding="utf-8-sig")
    return json.loads(text)


def cats(payload):
    if not isinstance(payload, dict):
        return []
    out = []
    for h in payload.get("commercial_category_hypotheses") or []:
        if isinstance(h, dict) and h.get("category_code"):
            out.append(str(h["category_code"]))
    return out


def main() -> None:
    dump = load("_phase8_immutable_dump.json")
    summary = load("_phase8_run_summary.json")
    forensic = load("_phase71_forensic.json")
    corpus = load("MODEL_CATEGORY_CALIBRATION_CORPUS.json")
    v61 = load("phase7_ab_v61_summary.json")
    abc = load("phase71_abc_summary.json")

    registry = set(summary["registry"])
    by_pid_corpus = {c["procurement_id"]: c for c in corpus["cases"]}
    forensic_by_pid = {c["PROCUREMENT_ID"]: c for c in forensic}
    runs_by_id = {int(r["id"]): r for r in dump["runs"]}

    # Canonical primary runs for deep focus (Phase 7 A/B v6_1)
    PRIMARY_RUN = {
        37082: 239,
        23591: 283,
        27355: 259,
        34517: 271,
    }

    # Representative corpus: 10 DIRECT + 10 NEG + 10 OBJECT + 4 extras = 34
    directs = [r for r in v61["results"]["v6_1"] if r["bucket"] == "CLEAR_DIRECT_POSITIVE"]
    negs = [r for r in v61["results"]["v6_1"] if r["bucket"] == "CLEAR_NEGATIVE"]
    # objects from phase71 abc v6_1
    objs = [
        r
        for r in abc["results"]["v6_1"]
        if r["bucket"] in ("OBJECT_CONSTRUCTION", "OBJECT_RELABELED")
    ]
    must = {37082, 23591, 27355, 34517}

    def pick(group, n, force_ids):
        chosen = []
        for r in group:
            if r["procurement_id"] in force_ids:
                chosen.append(r)
        for r in group:
            if len(chosen) >= n:
                break
            if r not in chosen:
                chosen.append(r)
        return chosen[:n]

    available_runs = set(runs_by_id.keys())
    # Dump-driven corpus: prefer lowest inference_run_id per procurement (Phase 7 before 7.1 re-runs)
    best_by_pid = {}
    for row in summary["summary"]:
        pid = int(row["procurement_id"])
        rid = int(row["inference_run_id"])
        if pid not in best_by_pid or rid < int(best_by_pid[pid]["inference_run_id"]):
            best_by_pid[pid] = row

    def corpus_bucket(pid: int) -> str:
        return str((by_pid_corpus.get(pid) or {}).get("bucket") or "UNKNOWN")

    def expected_of(pid: int):
        c = by_pid_corpus.get(pid) or {}
        return c.get("expected_exact_category"), c.get("expected_label_kind")

    directs_pids = [pid for pid, b in ((p, corpus_bucket(p)) for p in best_by_pid) if b == "CLEAR_DIRECT_POSITIVE"]
    neg_pids = [pid for pid, b in ((p, corpus_bucket(p)) for p in best_by_pid) if b == "CLEAR_NEGATIVE"]
    obj_pids = [
        pid
        for pid, b in ((p, corpus_bucket(p)) for p in best_by_pid)
        if b in ("OBJECT_CONSTRUCTION", "OBJECT_RELABELED")
    ]

    def pick_pids(pool, n, force):
        out = []
        for pid in force:
            if pid in pool and pid not in out:
                out.append(pid)
        for pid in sorted(pool):
            if len(out) >= n:
                break
            if pid not in out:
                out.append(pid)
        return out[:n]

    selected_pids = (
        pick_pids(directs_pids, 10, must)
        + pick_pids(neg_pids, 10, must)
        + pick_pids(obj_pids, 10, must)
    )
    # pad to 34
    for pid in sorted(best_by_pid.keys()):
        if len(selected_pids) >= 34:
            break
        if pid not in selected_pids:
            selected_pids.append(pid)
    selected_pids = selected_pids[:34]
    assert len(selected_pids) == 34
    assert len(set(selected_pids)) == 34

    selected = []
    for pid in selected_pids:
        exp, kind = expected_of(pid)
        rid = PRIMARY_RUN.get(pid, int(best_by_pid[pid]["inference_run_id"]))
        if rid not in available_runs:
            rid = int(best_by_pid[pid]["inference_run_id"])
        selected.append(
            {
                "procurement_id": pid,
                "bucket": corpus_bucket(pid),
                "expected_exact_category": exp,
                "expected_label_kind": kind,
                "inference_run_id": rid,
            }
        )

    def attribute(pid: int, run_id: int, bucket: str, expected: str | None, label_kind: str | None):
        run = runs_by_id.get(run_id)
        if not run:
            return {
                "procurement_id": pid,
                "inference_run_id": run_id,
                "bucket": bucket,
                "expected_exact_category": expected,
                "expected_label_kind": label_kind,
                "STATUS": "RUN_MISSING",
                "flags": {
                    "SOURCE_DATA_GAP": "NO",
                    "MODEL_INPUT_GAP": "YES",
                    "PYTHON_PREBIAS": "NO",
                    "PROCUREMENT_FORM_ERROR": "NO",
                    "OBJECT_CLASSIFICATION_ERROR": "NO",
                    "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR": "NO",
                    "CATEGORY_MAPPING_ERROR": "NO",
                    "INVALID_REGISTRY_CODE_GENERATION": "NO",
                    "VALIDATOR_REJECTED_MODEL_CATEGORY": "NO",
                    "ABSTENTION_ERROR": "NO",
                    "OBJECT_PRIOR_OVERREACH": "NO",
                    "POST_MODEL_BUSINESS_ERROR": "NO",
                    "PRESENTATION_ERROR": "NO",
                    "NO_ERROR": "NO",
                },
                "PRIMARY_ROOT_CAUSE": "MODEL_INPUT_GAP",
                "explanation": f"immutable run_id={run_id} not in Phase 8 dump",
                "raw_categories": [],
                "validated_categories": [],
                "invalid_raw_categories": [],
                "RAW_CATEGORY": None,
                "VALIDATED_CATEGORY": None,
                "SHADOW_ONLY": True,
            }
        raw = run.get("raw_model_json") or {}
        val = run.get("validated_model_result") or {}
        raw_cats = cats(raw)
        val_cats = cats(val)
        invalid = [c for c in raw_cats if c not in registry]
        oc = raw.get("object_classification") or {}
        form = raw.get("procurement_form")
        empty_raw = raw.get("empty_hypothesis_status")
        empty_val = val.get("empty_hypothesis_status")
        validator_removed = bool(raw_cats) and not val_cats
        foc = forensic_by_pid.get(pid)
        title_hints = (foc or {}).get("TITLE_HINTS_VISIBLE_TO_MODEL") or []
        okpd_priors = (foc or {}).get("OKPD_PRIORS_VISIBLE_TO_MODEL") or []
        form_prior = (foc or {}).get("PROCUREMENT_FORM_PRIOR")

        flags = {
            "SOURCE_DATA_GAP": "NO",
            "MODEL_INPUT_GAP": "NO",
            "PYTHON_PREBIAS": "NO",
            "PROCUREMENT_FORM_ERROR": "NO",
            "OBJECT_CLASSIFICATION_ERROR": "NO",
            "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR": "NO",
            "CATEGORY_MAPPING_ERROR": "NO",
            "INVALID_REGISTRY_CODE_GENERATION": "YES" if invalid else "NO",
            "VALIDATOR_REJECTED_MODEL_CATEGORY": "YES" if validator_removed else "NO",
            "ABSTENTION_ERROR": "NO",
            "OBJECT_PRIOR_OVERREACH": "NO",
            "POST_MODEL_BUSINESS_ERROR": "NO",
            "PRESENTATION_ERROR": "NO",
            "NO_ERROR": "NO",
        }

        primary = "NO_ERROR"
        note = ""

        # Focus case overrides with deep forensic
        if pid == 37082:
            flags.update(
                {
                    "CATEGORY_MAPPING_ERROR": "YES",
                    "INVALID_REGISTRY_CODE_GENERATION": "YES",
                    "VALIDATOR_REJECTED_MODEL_CATEGORY": "YES",
                    "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR": "NO",
                    "ABSTENTION_ERROR": "YES",  # empty_hypothesis_status remained null after wipe
                }
            )
            primary = "CATEGORY_MAPPING_ERROR"
            note = (
                "Model understood monoblock/PC goods (object_subtype=COMPUTER_COMPONENTS) but "
                "emitted invalid registry code computer_components instead of computers; "
                "validator emptied hypotheses."
            )
        elif pid == 23591:
            # Primary evidence: run 283 cable/CABLE — wrong product family vs storm-sewer equipment
            flags.update(
                {
                    "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR": "YES",
                    "OBJECT_CLASSIFICATION_ERROR": "YES",
                    "CATEGORY_MAPPING_ERROR": "NO",
                    "INVALID_REGISTRY_CODE_GENERATION": "YES",
                    "VALIDATOR_REJECTED_MODEL_CATEGORY": "YES",
                    "PYTHON_PREBIAS": "NO",
                    "ABSTENTION_ERROR": "YES",
                }
            )
            primary = "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"
            note = (
                "Title/hints/map rule all point to drainage_water_management; RAW emitted "
                "invalid cable with object_subtype=CABLE (wrong product family). Phase 7.1 "
                "re-run 476 emitted invalid equipment — still not drainage. Not the same "
                "near-miss taxonomy failure as 37082."
            )
        elif pid == 27355:
            flags.update(
                {
                    "PROCUREMENT_FORM_ERROR": "YES",
                    "OBJECT_PRIOR_OVERREACH": "YES",
                    "OBJECT_CLASSIFICATION_ERROR": "YES",
                    "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR": "YES",
                }
            )
            primary = "OBJECT_PRIOR_OVERREACH"
            note = (
                "Service/metering verification; form prior DESIGN_ONLY but model copied "
                "OBJECT EXAMPLE (ROAD/ROAD_REPAIR + curbstone contextual)."
            )
        elif pid == 34517:
            flags.update(
                {
                    "OBJECT_PRIOR_OVERREACH": "YES",
                    "OBJECT_CLASSIFICATION_ERROR": "YES",
                }
            )
            primary = "OBJECT_PRIOR_OVERREACH"
            note = (
                "Indoor room repair; model emitted lighting contextual with ROAD object "
                "skeleton (example leakage / object-mode overreach). Corpus later "
                "OBJECT_RELABELED — not a hard CLEAR_NEGATIVE."
            )
        else:
            # Heuristic attribution for corpus
            if bucket == "CLEAR_DIRECT_POSITIVE" and expected:
                if expected in val_cats:
                    primary = "NO_ERROR"
                    flags["NO_ERROR"] = "YES"
                    note = "Validated category matches expected."
                elif invalid and any(
                    expected.split("_")[0] in c or c.split("_")[0] in expected
                    for c in invalid
                ):
                    flags["CATEGORY_MAPPING_ERROR"] = "YES"
                    flags["INVALID_REGISTRY_CODE_GENERATION"] = "YES"
                    flags["VALIDATOR_REJECTED_MODEL_CATEGORY"] = "YES"
                    flags["ABSTENTION_ERROR"] = "YES" if empty_val is None else "NO"
                    primary = "CATEGORY_MAPPING_ERROR"
                    note = f"Near-miss invalid code {invalid} for expected {expected}."
                elif invalid:
                    flags["ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"] = "YES"
                    flags["INVALID_REGISTRY_CODE_GENERATION"] = "YES"
                    flags["VALIDATOR_REJECTED_MODEL_CATEGORY"] = "YES"
                    flags["ABSTENTION_ERROR"] = "YES" if empty_val is None else "NO"
                    primary = "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"
                    note = f"Invalid RAW {invalid}; expected {expected}; not near-miss."
                elif not val_cats:
                    flags["ABSTENTION_ERROR"] = "YES"
                    primary = "ABSTENTION_ERROR"
                    note = "Silent/empty validated result for expected direct category."
                elif expected not in val_cats:
                    flags["CATEGORY_MAPPING_ERROR"] = "YES"
                    primary = "CATEGORY_MAPPING_ERROR"
                    note = f"Validated {val_cats} != expected {expected}."
            elif bucket == "CLEAR_NEGATIVE":
                if not val_cats and not raw_cats:
                    if empty_val in ("NO_COMMERCIAL_ENTRY", "INSUFFICIENT_EVIDENCE", "REVIEW_REQUIRED"):
                        primary = "NO_ERROR"
                        flags["NO_ERROR"] = "YES"
                        note = "Correct empty with status."
                    else:
                        # empty without status — soft contract issue but commercially OK for neg
                        if form in ("CONSTRUCTION_WORKS",) and (oc.get("object_type") in ("ROAD",)):
                            flags["OBJECT_PRIOR_OVERREACH"] = "YES"
                            primary = "OBJECT_PRIOR_OVERREACH"
                            note = "Negative service/goods but object skeleton present."
                        else:
                            flags["ABSTENTION_ERROR"] = "YES"
                            primary = "ABSTENTION_ERROR"
                            note = "Empty hyps with null empty_hypothesis_status (contract)."
                elif invalid and validator_removed:
                    # understood out-of-registry product, invented code, validator wiped
                    flags["INVALID_REGISTRY_CODE_GENERATION"] = "YES"
                    flags["VALIDATOR_REJECTED_MODEL_CATEGORY"] = "YES"
                    flags["ABSTENTION_ERROR"] = "YES" if empty_val is None else "NO"
                    # commercially ends empty — primary is invalid code instead of NCE
                    primary = "INVALID_REGISTRY_CODE_GENERATION"
                    note = (
                        f"Outside-registry item expressed as invented code {invalid}; "
                        "validator emptied; should have been []+NO_COMMERCIAL_ENTRY."
                    )
                elif val_cats:
                    if form in ("CONSTRUCTION_WORKS", "DESIGN_ONLY") or oc.get("object_type") in (
                        "ROAD",
                        "BUILDING",
                    ):
                        flags["OBJECT_PRIOR_OVERREACH"] = "YES"
                        primary = "OBJECT_PRIOR_OVERREACH"
                    else:
                        flags["CATEGORY_MAPPING_ERROR"] = "YES"
                        primary = "CATEGORY_MAPPING_ERROR"
                    note = f"Non-empty validated categories on negative: {val_cats}."
            elif bucket in ("OBJECT_CONSTRUCTION", "OBJECT_RELABELED"):
                if val_cats and any(
                    (h.get("opportunity_track") if isinstance(h, dict) else None)
                    == "DIRECT_SUPPLY"
                    for h in (val.get("commercial_category_hypotheses") or [])
                ):
                    flags["OBJECT_PRIOR_OVERREACH"] = "YES"
                    primary = "OBJECT_PRIOR_OVERREACH"
                    note = "Object case emitted DIRECT_SUPPLY track."
                elif invalid:
                    flags["INVALID_REGISTRY_CODE_GENERATION"] = "YES"
                    flags["VALIDATOR_REJECTED_MODEL_CATEGORY"] = (
                        "YES" if validator_removed else "NO"
                    )
                    primary = "INVALID_REGISTRY_CODE_GENERATION"
                    note = f"Object case invalid codes {invalid}."
                elif not val_cats and empty_val in (
                    "INSUFFICIENT_EVIDENCE",
                    "REVIEW_REQUIRED",
                    "NO_COMMERCIAL_ENTRY",
                ):
                    primary = "NO_ERROR"
                    flags["NO_ERROR"] = "YES"
                    note = "Empty contextual with status — acceptable for weak object."
                elif val_cats:
                    primary = "NO_ERROR"
                    flags["NO_ERROR"] = "YES"
                    note = f"Object contextual hyps retained: {val_cats}."
                else:
                    flags["ABSTENTION_ERROR"] = "YES"
                    primary = "ABSTENTION_ERROR"
                    note = "Empty object result without empty_hypothesis_status."
            else:
                note = f"Bucket {bucket} — heuristic only."

        return {
            "procurement_id": pid,
            "bucket": bucket,
            "expected_label_kind": label_kind,
            "expected_exact_category": expected,
            "inference_run_id": run_id,
            "run_kind": run.get("run_kind"),
            "prompt_version": run.get("prompt_version"),
            "model_name": run.get("model_name"),
            "prompt_hash": run.get("prompt_hash"),
            "raw_categories": raw_cats,
            "validated_categories": val_cats,
            "invalid_raw_categories": invalid,
            "procurement_form_raw": form,
            "object_type": oc.get("object_type"),
            "object_subtype": oc.get("object_subtype"),
            "work_stage": oc.get("work_stage"),
            "empty_hypothesis_status_raw": empty_raw,
            "empty_hypothesis_status_validated": empty_val,
            "RAW_CATEGORY": raw_cats[0] if raw_cats else None,
            "VALIDATED_CATEGORY": val_cats[0] if val_cats else None,
            "RAW_CATEGORY_VALID_IN_REGISTRY": (
                "YES" if raw_cats and not invalid else ("N/A" if not raw_cats else "NO")
            ),
            "VALIDATOR_REMOVED_CATEGORY": "YES" if validator_removed else "NO",
            "VALIDATOR_CHANGED_SEMANTICS": "YES"
            if raw_cats != val_cats
            else "NO",
            "title_hints_forensic": title_hints,
            "okpd_priors_forensic": okpd_priors,
            "form_prior_forensic": form_prior,
            "flags": flags,
            "PRIMARY_ROOT_CAUSE": primary,
            "explanation": note,
            "SHADOW_ONLY": run.get("run_kind") == "SHADOW",
        }

    traced = []
    for r in selected:
        pid = r["procurement_id"]
        # Prefer primary forensic runs for focus IDs; else the selected immutable run.
        run_id = PRIMARY_RUN.get(pid, int(r["inference_run_id"]))
        if run_id not in available_runs:
            run_id = int(r["inference_run_id"])
        traced.append(
            attribute(
                pid,
                run_id,
                r["bucket"],
                r.get("expected_exact_category"),
                r.get("expected_label_kind"),
            )
        )

    # Deep case payloads from forensic
    deep = {}
    for pid in (37082, 23591, 27355, 34517):
        deep[str(pid)] = forensic_by_pid.get(pid)

    # Failure distribution
    dist = Counter(t["PRIMARY_ROOT_CAUSE"] for t in traced)
    flag_lists = defaultdict(list)
    for t in traced:
        for k, v in t["flags"].items():
            if v == "YES" and k != "NO_ERROR":
                flag_lists[k].append(t["procurement_id"])

    # Model input field audit from model_input.py keys
    mi_keys = [
        "model_input_version",
        "procurement_id",
        "procurement_number",
        "source_contour",
        "source_table",
        "source_id",
        "source_origin",
        "title",
        "official_description",
        "normalized_lifecycle",
        "source_start_date",
        "source_end_date",
        "procurement_start_at",
        "procurement_end_at",
        "procurement_start_at_provenance",
        "procurement_end_at_provenance",
        "published_at",
        "published_at_provenance",
        "source_created_at",
        "procurement_duration_days",
        "remaining_days",
        "remaining_ratio",
        "deadline_pressure",
        "procurement_age_days",
        "award_age_days",
        "execution_remaining_days",
        "commercial_timing_value",
        "commercial_timing_version",
        "commercial_timing_confidence",
        "commercial_timing_start_provenance",
        "source_delivery_start_date",
        "source_delivery_end_date",
        "delivery_start_at",
        "delivery_end_at",
        "customer_name",
        "customer_inn",
        "purchasing_organization",
        "winner_name",
        "winner_inn",
        "winner_role",
        "award_at",
        "initial_price",
        "final_contract_price",
        "price_reduction_percent",
        "contract_execution_end_at",
        "execution_active",
        "primary_commercial_region",
        "region_provenance",
        "okpd_codes",
        "okpd_names",
        "okpd_hierarchy",
        "COMMERCIAL_PRODUCT_PRIORS",
        "CONTEXTUAL_RESEARCH_PRIORS",
        "DIRECT_CABLE_EXPECTED_RESULT",
        "source_card_url",
        "source_card_url_type",
        "document_link_count",
        "unique_document_count",
    ]

    def classify_field(k: str) -> str:
        if k in (
            "title",
            "official_description",
            "okpd_codes",
            "okpd_names",
            "okpd_hierarchy",
            "source_contour",
        ):
            return "SEMANTIC_CLASSIFICATION_REQUIRED"
        if k in (
            "COMMERCIAL_PRODUCT_PRIORS",
            "CONTEXTUAL_RESEARCH_PRIORS",
            "DIRECT_CABLE_EXPECTED_RESULT",
        ):
            return "POTENTIALLY_HARMFUL_ANCHOR"
        if k in (
            "commercial_timing_value",
            "commercial_timing_version",
            "commercial_timing_confidence",
            "commercial_timing_start_provenance",
            "remaining_days",
            "remaining_ratio",
            "deadline_pressure",
            "procurement_age_days",
            "award_age_days",
            "execution_remaining_days",
            "initial_price",
            "final_contract_price",
            "price_reduction_percent",
        ):
            return "LATER_SCORING_ONLY"
        if k in (
            "normalized_lifecycle",
            "source_start_date",
            "source_end_date",
            "procurement_start_at",
            "procurement_end_at",
            "procurement_start_at_provenance",
            "procurement_end_at_provenance",
            "published_at",
            "published_at_provenance",
            "source_created_at",
            "procurement_duration_days",
            "source_delivery_start_date",
            "source_delivery_end_date",
            "delivery_start_at",
            "delivery_end_at",
            "award_at",
            "contract_execution_end_at",
            "execution_active",
            "winner_name",
            "winner_inn",
            "winner_role",
        ):
            return "LIFECYCLE_ONLY"
        if k in (
            "source_card_url",
            "source_card_url_type",
            "customer_name",
            "customer_inn",
            "purchasing_organization",
            "primary_commercial_region",
            "region_provenance",
            "procurement_number",
            "source_table",
            "source_id",
            "source_origin",
            "procurement_id",
            "model_input_version",
        ):
            return "UI_ONLY" if "url" in k or k in ("customer_name", "purchasing_organization") else "NOT_REQUIRED_FOR_ROUTING"
        if k in ("document_link_count", "unique_document_count"):
            return "POTENTIALLY_HARMFUL_ANCHOR"
        if k in ("okpd_codes", "okpd_names"):
            return "COMMERCIAL_MAPPING_REQUIRED"
        return "NOT_REQUIRED_FOR_ROUTING"

    # refine: okpd also commercial mapping
    field_audit = []
    for k in mi_keys:
        cls = classify_field(k)
        if k in ("okpd_codes", "okpd_names", "okpd_hierarchy", "title", "official_description"):
            # dual use — record primary semantic + mapping note
            if k.startswith("okpd"):
                cls = "COMMERCIAL_MAPPING_REQUIRED"
            else:
                cls = "SEMANTIC_CLASSIFICATION_REQUIRED"
        field_audit.append({"field": k, "class": cls})

    # Prompt question decomposition from v5 + v6_1 contracts
    questions = [
        {
            "QUESTION_ID": "Q1_PROCUREMENT_FORM",
            "PLAIN_RUSSIAN_QUESTION": "Какая форма закупки (поставка товара / СМР / проектирование / услуги / иное)?",
            "OUTPUT_FIELD": "procurement_form",
            "INPUT_FACTS_USED": ["title", "okpd_codes", "okpd_names", "source_contour"],
            "PYTHON_PRIORS_USED": ["procurement_form_prior"],
            "REQUIRES_COMMERCIAL_TAXONOMY": "no",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "SEMANTIC_CLASSIFICATION",
        },
        {
            "QUESTION_ID": "Q2_OBJECT_CLASSIFICATION",
            "PLAIN_RUSSIAN_QUESTION": "Что это за объект/товар и на какой стадии работ?",
            "OUTPUT_FIELD": "object_classification",
            "INPUT_FACTS_USED": ["title", "okpd_names"],
            "PYTHON_PRIORS_USED": [],
            "REQUIRES_COMMERCIAL_TAXONOMY": "no",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "FACT_EXTRACTION",
        },
        {
            "QUESTION_ID": "Q3_ACTUAL_PURCHASE_ITEM",
            "PLAIN_RUSSIAN_QUESTION": "Что фактически закупается по заголовку/ОКПД?",
            "OUTPUT_FIELD": "object_classification.object_subtype + reason_codes",
            "INPUT_FACTS_USED": ["title", "official_description", "okpd_codes", "okpd_names"],
            "PYTHON_PRIORS_USED": ["title_hints (subcategory exposure only)"],
            "REQUIRES_COMMERCIAL_TAXONOMY": "no",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "FACT_EXTRACTION",
        },
        {
            "QUESTION_ID": "Q4_REGISTRY_CATEGORY_MAP",
            "PLAIN_RUSSIAN_QUESTION": "Какой ACTIVE код коммерческого реестра соответствует закупаемому?",
            "OUTPUT_FIELD": "commercial_category_hypotheses[].category_code",
            "INPUT_FACTS_USED": ["title", "okpd_*", "ALLOWED_COMMERCIAL_CATEGORY_CODES", "registry_desc"],
            "PYTHON_PRIORS_USED": ["COMMERCIAL_PRODUCT_PRIORS", "OKPD priors", "title_hints"],
            "REQUIRES_COMMERCIAL_TAXONOMY": "yes",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "COMMERCIAL_TAXONOMY_MAPPING",
        },
        {
            "QUESTION_ID": "Q5_OPPORTUNITY_TRACK",
            "PLAIN_RUSSIAN_QUESTION": "Это прямая поставка или встроенный/проектный материал объекта?",
            "OUTPUT_FIELD": "commercial_category_hypotheses[].opportunity_track",
            "INPUT_FACTS_USED": ["procurement_form", "title"],
            "PYTHON_PRIORS_USED": ["CONTEXTUAL_RESEARCH_PRIORS"],
            "REQUIRES_COMMERCIAL_TAXONOMY": "yes",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "partial",
            "CLASS": "SEMANTIC_CLASSIFICATION",
        },
        {
            "QUESTION_ID": "Q6_OBJECT_PRIOR_PRODUCTS",
            "PLAIN_RUSSIAN_QUESTION": "Какие продукты реестра правдоподобны на этом объекте строительства/проектирования?",
            "OUTPUT_FIELD": "commercial_category_hypotheses (contextual) + object_context",
            "INPUT_FACTS_USED": ["title", "okpd_*", "procurement_form"],
            "PYTHON_PRIORS_USED": ["CONTEXTUAL_RESEARCH_PRIORS"],
            "REQUIRES_COMMERCIAL_TAXONOMY": "yes",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "OBJECT_CONTEXT_PREDICTION",
        },
        {
            "QUESTION_ID": "Q7_DOCUMENT_CONFIRMED_PRODUCTS",
            "PLAIN_RUSSIAN_QUESTION": "Какие продукты уже подтверждены документами?",
            "OUTPUT_FIELD": "evidence_role / confirmation_required / document_research_priority",
            "INPUT_FACTS_USED": ["document_link_count", "unique_document_count"],
            "PYTHON_PRIORS_USED": [],
            "REQUIRES_COMMERCIAL_TAXONOMY": "yes",
            "REQUIRES_DOCUMENT_CONTENT": "yes",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "no",
            "CLASS": "RESEARCH_PLANNING",
        },
        {
            "QUESTION_ID": "Q8_ABSTENTION",
            "PLAIN_RUSSIAN_QUESTION": "Нужно ли отказаться от гипотез и с каким статусом пустоты?",
            "OUTPUT_FIELD": "empty_hypothesis_status + empty_hypothesis_reason_codes",
            "INPUT_FACTS_USED": ["title", "okpd_*", "registry allow-list"],
            "PYTHON_PRIORS_USED": ["DIRECT_CABLE_EXPECTED_RESULT"],
            "REQUIRES_COMMERCIAL_TAXONOMY": "yes",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "ABSTENTION",
        },
        {
            "QUESTION_ID": "Q9_RESEARCH_ACTION",
            "PLAIN_RUSSIAN_QUESTION": "Какую глубину исследования документов назначить?",
            "OUTPUT_FIELD": "overall_research_action + document_research_priority",
            "INPUT_FACTS_USED": ["document_*_count", "procurement_form", "hypotheses"],
            "PYTHON_PRIORS_USED": [],
            "REQUIRES_COMMERCIAL_TAXONOMY": "no",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "RESEARCH_PLANNING",
        },
        {
            "QUESTION_ID": "Q10_MATERIAL_SIGNALS",
            "PLAIN_RUSSIAN_QUESTION": "Какие материальные/брендовые сигналы видны из карточки?",
            "OUTPUT_FIELD": "material_signals / brands / work_methods / application_areas",
            "INPUT_FACTS_USED": ["title", "okpd_names"],
            "PYTHON_PRIORS_USED": [],
            "REQUIRES_COMMERCIAL_TAXONOMY": "no",
            "REQUIRES_DOCUMENT_CONTENT": "no",
            "CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH": "yes",
            "CLASS": "FACT_EXTRACTION",
        },
    ]

    # Document boundary proof from model_input keys + prompt (no document text fields)
    doc_boundary = {
        "DOCUMENT_CONTENT_SENT_TO_ROUTING_MODEL": "NO",
        "DOCUMENT_TEXT_SENT_TO_ROUTING_MODEL": "NO",
        "DOCUMENT_NAMES_SENT_TO_ROUTING_MODEL": "NO",
        "DOCUMENT_EVIDENCE_SENT_TO_ROUTING_MODEL": "NO",
        "WHAT_IS_SENT": [
            "document_link_count",
            "unique_document_count",
        ],
        "NOTE": (
            "Canonical card may resolve document_links_summary (names/URLs) but "
            "V3_ROUTING_MODEL_INPUT_V3 excludes link arrays; only counts enter the prompt JSON."
        ),
        "FIELDS_ASKING_UNSEEN_DOCUMENTS": [
            "document_research_priority",
            "confirmation_required for CONTEXTUAL_RESEARCH_PRIOR",
            "evidence that products are confirmed in documents (Q7)",
            "MODE B object hypotheses framed as requiring document confirmation",
        ],
    }

    semantic_split = {
        "ACTUAL_PURCHASE_VS_REGISTRY_MAPPING_MIXED": "YES",
        "ACTUAL_PURCHASE_VS_OBJECT_PRIOR_MIXED": "YES",
        "OBJECT_PRIOR_VS_CONFIRMED_DOCUMENT_EVIDENCE_MIXED": "YES",
        "EVIDENCE": (
            "Single inference asks form + object_classification + registry category_code + "
            "contextual object priors + document_research_priority/confirmation_required "
            "without document text. Prompt MODE A/B and examples mix purchase mapping with "
            "object-prior prediction."
        ),
    }

    case_23591 = next(t for t in traced if t["procurement_id"] == 23591)
    case_37082 = next(t for t in traced if t["procurement_id"] == 37082)

    compare = {
        "DO_37082_AND_23591_SHARE_THE_SAME_FAILURE_MECHANISM": "NO",
        "table": [
            {
                "Dimension": "Source sufficient?",
                "37082": "YES",
                "23591": "YES",
            },
            {
                "Dimension": "Correct procurement form?",
                "37082": "YES (DIRECT_GOODS_PURCHASE)",
                "23591": "YES (DIRECT_GOODS_PURCHASE)",
            },
            {
                "Dimension": "Model understood literal item?",
                "37082": "YES (computer/monoblock family)",
                "23591": "NO (RAW subtype CABLE / later EQUIPMENT)",
            },
            {
                "Dimension": "Model understood object?",
                "37082": "N/A (goods supply)",
                "23591": "N/A (goods supply)",
            },
            {
                "Dimension": "Correct registry category visible?",
                "37082": "YES (computers)",
                "23591": "YES (drainage_water_management)",
            },
            {
                "Dimension": "Correct category prior visible?",
                "37082": "YES (OKPD prior computers + title_hints)",
                "23591": "YES (title_hints=[drainage_water_management]; OKPD priors=[])",
            },
            {
                "Dimension": "Model emitted semantic equivalent?",
                "37082": "NEAR (computer_components)",
                "23591": "NO (cable / equipment)",
            },
            {
                "Dimension": "Model emitted invalid code?",
                "37082": "YES",
                "23591": "YES",
            },
            {
                "Dimension": "Validator caused empty result?",
                "37082": "YES",
                "23591": "YES",
            },
            {
                "Dimension": "True abstention?",
                "37082": "NO",
                "23591": "NO",
            },
            {
                "Dimension": "Primary failure class",
                "37082": "CATEGORY_MAPPING_ERROR",
                "23591": "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR",
            },
        ],
        "shared_surface": (
            "Both SHADOW runs end as validated empty after invalid RAW category rejection; "
            "that shared surface is NOT the same root mechanism."
        ),
    }

    out = {
        "wip": "CRM-V3-MODEL-AUTHORITY-RESTORATION-1",
        "phase": "8",
        "authority": {
            "PRODUCTION_MODEL": "qwen2.5:7b",
            "PRODUCTION_PROMPT_VERSION": "v3_category_centric_routing_7b_v5",
            "AUDIT_PROMPT_VERSION": "v3_category_centric_routing_7b_v6_1",
            "MODEL_INPUT_VERSION": "V3_ROUTING_MODEL_INPUT_V3",
            "NOTE": (
                "Deep residual forensics and Phase 7/7.1 immutable SHADOW runs use frozen "
                "v6_1. Production default remains v5 — not changed in Phase 8."
            ),
        },
        "TRACED_CASES": len(traced),
        "DIRECT_CASES": sum(1 for t in traced if t.get("bucket") == "CLEAR_DIRECT_POSITIVE"),
        "NEGATIVE_CASES": sum(1 for t in traced if t.get("bucket") == "CLEAR_NEGATIVE"),
        "OBJECT_CASES": sum(
            1
            for t in traced
            if t.get("bucket") in ("OBJECT_CONSTRUCTION", "OBJECT_RELABELED")
        ),
        "PRIMARY_FOCUS_RUNS": PRIMARY_RUN,
        "cases": traced,
        "deep_forensic": {
            "37082": _slim_forensic(deep.get("37082")),
            "23591": _slim_forensic(deep.get("23591")),
            "27355": _slim_forensic(deep.get("27355")),
            "34517": _slim_forensic(deep.get("34517")),
        },
        "compare_37082_vs_23591": compare,
        "CASE_37082_PRIMARY_ROOT_CAUSE": "CATEGORY_MAPPING_ERROR",
        "CASE_23591_PRIMARY_ROOT_CAUSE": case_23591["PRIMARY_ROOT_CAUSE"],
        "failure_distribution": dict(dist),
        "flag_case_lists": {k: v for k, v in flag_lists.items()},
        "document_boundary": doc_boundary,
        "semantic_split": semantic_split,
        "questions": questions,
        "field_audit": field_audit,
        "MODEL_VALIDATED_MUTATED": "NO",
        "PRODUCTION_MODEL_CHANGED": "NO",
        "PRODUCTION_PROMPT_CHANGED": "NO",
        "PRODUCTION_MUTATIONS": 0,
        "active_registry_at_dump": sorted(registry),
        "23591_rerun_note": {
            "phase7_run_283": "RAW cable / CABLE",
            "phase71_run_476": "RAW equipment / EQUIPMENT",
            "both": "invalid + validator empty; neither drainage_water_management",
        },
    }

    (REP / "model_decision_trace_cases.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    write_reports(out, forensic_by_pid, runs_by_id)
    print(
        json.dumps(
            {
                "TRACED_CASES": out["TRACED_CASES"],
                "DIRECT": out["DIRECT_CASES"],
                "NEG": out["NEGATIVE_CASES"],
                "OBJ": out["OBJECT_CASES"],
                "dist": out["failure_distribution"],
                "23591": out["CASE_23591_PRIMARY_ROOT_CAUSE"],
                "same_mech": compare["DO_37082_AND_23591_SHARE_THE_SAME_FAILURE_MECHANISM"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _slim_forensic(foc):
    if not foc:
        return None
    mi = (foc.get("MODEL_INPUT") or {}).get("v3_model_input") or {}
    return {
        "TITLE": foc.get("TITLE"),
        "OKPD_CODE": foc.get("OKPD_CODE"),
        "OKPD_NAME": foc.get("OKPD_NAME"),
        "model_input_version": mi.get("model_input_version"),
        "model_input_hash": (foc.get("MODEL_INPUT") or {}).get("v3_model_input_hash"),
        "PROCUREMENT_FORM_PRIOR": foc.get("PROCUREMENT_FORM_PRIOR"),
        "TITLE_HINTS_VISIBLE_TO_MODEL": foc.get("TITLE_HINTS_VISIBLE_TO_MODEL"),
        "OKPD_PRIORS_VISIBLE_TO_MODEL": foc.get("OKPD_PRIORS_VISIBLE_TO_MODEL"),
        "REGISTRY_CODES_VISIBLE_TO_MODEL": foc.get("REGISTRY_CODES_VISIBLE_TO_MODEL"),
        "PROMPT_VERSION_REBUILT": foc.get("PROMPT_VERSION_REBUILT"),
        "PROMPT_CHARS": foc.get("PROMPT_CHARS"),
        "INFERENCE_RUN_ID": foc.get("INFERENCE_RUN_ID"),
        "RAW_RESPONSE": foc.get("RAW_RESPONSE"),
        "VALIDATED_RESPONSE": foc.get("VALIDATED_RESPONSE"),
        "COMMERCIAL_PRODUCT_PRIORS": mi.get("COMMERCIAL_PRODUCT_PRIORS"),
        "CONTEXTUAL_RESEARCH_PRIORS": mi.get("CONTEXTUAL_RESEARCH_PRIORS"),
        "DIRECT_CABLE_EXPECTED_RESULT": mi.get("DIRECT_CABLE_EXPECTED_RESULT"),
        "document_link_count": mi.get("document_link_count"),
        "unique_document_count": mi.get("unique_document_count"),
        "official_description": mi.get("official_description"),
    }


def write_reports(out, forensic_by_pid, runs_by_id):
    f235 = forensic_by_pid[23591]
    mi = (f235.get("MODEL_INPUT") or {})
    v3 = mi.get("v3_model_input") or {}
    card = (mi.get("canonical_card") or {})

    def md_table(rows):
        if not rows:
            return ""
        keys = list(rows[0].keys())
        lines = ["| " + " | ".join(keys) + " |", "| " + " | ".join("---" for _ in keys) + " |"]
        for r in rows:
            lines.append("| " + " | ".join(str(r[k]) for k in keys) + " |")
        return "\n".join(lines)

    # MODEL_DECISION_TRACE_AUDIT.md
    audit = f"""# MODEL_DECISION_TRACE_AUDIT.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1` / **PHASE 8** (audit only)

## Authority

| Item | Value |
|--|--|
| PRODUCTION_MODEL | qwen2.5:7b |
| PRODUCTION_PROMPT_VERSION | v3_category_centric_routing_7b_v5 |
| AUDIT_SHADOW_PROMPT | v3_category_centric_routing_7b_v6_1 (Phase 7/7.1 immutable) |
| MODEL_INPUT_VERSION | V3_ROUTING_MODEL_INPUT_V3 |
| MODEL_VALIDATED_MUTATED | NO |
| PRODUCTION_MUTATIONS | 0 |

Phase 8 does **not** change production prompt/model. Residual forensics use frozen SHADOW v6_1 runs.

## Pipeline (proven)

```
SOURCE FACTS
→ CANONICAL CARD (V2)
→ V3_ROUTING_MODEL_INPUT_V3
→ PYTHON priors / form prior / title hints / OKPD priors (prompt-adjacent)
→ EXACT QWEN PROMPT (v5 prod / v6_1 audit shadow)
→ RAW MODEL RESPONSE (immutable crm_v3_model_inference_runs.raw_model_json)
→ VALIDATED MODEL RESULT (registry allow-list filter; no invention)
→ BUSINESS POSTPROCESSING (contextual priors, scores, medals) — separate attribution
→ UI projection
```

Document content is **not** in first-pass routing input (counts only).

---

## CASE 23591 — pipeline dump

Expert label: `EXPECTED_EXACT_CATEGORY=drainage_water_management`  
Evidence base: immutable SHADOW `inference_run_id=283` (`v3_category_centric_routing_7b_v6_1`) + Phase 7.1 re-run `476` + forensic rebuild in `_phase71_forensic.json`  
SHADOW only: YES (not production-authoritative)

### SOURCE FACTS

| Field | Value | Kind |
|--|--|--|
| title | Поставка оборудования ливневой канализации БМК Сосневская, г. Иваново 2026 г. для нужд филиала "Владимирский" ПАО "Т Плюс"(ИвТС) (4548581) | SOURCE FACT |
| official_description | null | SOURCE_NOT_AVAILABLE |
| OKPD code | 22.23.13.194 | SOURCE FACT |
| OKPD name | Резервуары, цистерны, баки и аналогичные емкости пластмассовые вместимостью свыше 300 л из поливинилхлорида | SOURCE FACT |
| all exact OKPD | ["22.23.13.194"] | SOURCE FACT |
| price | 1659743.39 | SOURCE FACT |
| law | 223_FZ / CORPORATE_223FZ | SOURCE FACT / DERIVED contour |
| customer | ПАО "Т ПЛЮС" | SOURCE FACT |
| region | delivery_region text "Московская область"; address Иваново | SOURCE FACT (inconsistent geography in source) |
| lifecycle | WAITING_SOURCE_OUTCOME | DERIVED |
| source identity | reestr_contract_223_fz / source_id=156304 / contract 32616265292 | SOURCE FACT |

### CANONICAL CARD

Card version V2. Relevant fields before model-input reduction:

- SOURCE FACT: title, OKPD, price, customer, tender_link, document_links_summary (2 zip names/URLs on card)
- DERIVED: normalized_lifecycle, tender_clock, commercial_timing_value, routing_ready=false (WAITING_NOT_ROUTABLE), region_provenance=SOURCE_DELIVERY_REGION
- official_description_provenance=`SOURCE_NOT_AVAILABLE`

`document_links_summary` exists on the **card** but is **stripped** from `V3_ROUTING_MODEL_INPUT_V3` (counts only).

### PYTHON BEFORE MODEL

| Signal | Value | VISIBLE_TO_MODEL |
|--|--|--|
| procurement_form_prior | DIRECT_GOODS_PURCHASE | YES (heuristic form prior in prompt) |
| commercial_product_priors | [] | YES (empty list in model input JSON) |
| contextual_research_priors | [] | YES (empty) |
| title_hints | [drainage_water_management] | YES (drives subcategory exposure; category listed in registry block) |
| OKPD prior matches | [] | YES (empty priors JSON in prompt) |
| allowed registry categories | includes drainage_water_management; does **not** include `cable` | YES |
| subcategory details | exposed for hint-supported drainage | YES (compact registry) |
| DIRECT_CABLE_EXPECTED_RESULT | NO_COMMERCIAL_ENTRY | YES |
| document counts | link=2 unique=2 | YES |

### ACTUAL MODEL INPUT

- model_input_version=`V3_ROUTING_MODEL_INPUT_V3`
- model_input_hash=`3b7aa959b14d028d7376bf478bc09384d2109bd40d41266ae6b4dff2f9237678`
- Exact persisted/rebuilt object in forensic `MODEL_INPUT.v3_model_input` (not approximated).

### ACTUAL MODEL QUESTION / PROMPT

- prompt_version=`v3_category_centric_routing_7b_v6_1`
- prompt size≈21203 chars (forensic rebuild)
- model=`qwen2.5:7b`
- prompt_hash on run 283: see immutable dump

What Qwen was asked:

1. Yes — understand the literal purchased item (MODE A / DIRECT map from title).
2. Also anchored toward object-mode via OBJECT EXAMPLE (curbstone/ROAD) in the same prompt.
3. `drainage_water_management` present in: commercial registry YES; OKPD prior NO; contextual prior NO; title hint YES.
4. Lighting / cable_support examples are salient in POSITIVE EXAMPLE blocks; map rule includes `дренаж/ливнев→drainage_water_management` and `кабельн* лоток→cable_support_systems`.

### RAW MODEL RESPONSE (run 283)

```json
{json.dumps(f235.get('RAW_RESPONSE'), ensure_ascii=False, indent=2)}
```

Phase 7.1 re-run 476 RAW categories: `["equipment"]`, object_subtype=`EQUIPMENT` (also invalid; still not drainage).

### VALIDATED MODEL

```json
{json.dumps(f235.get('VALIDATED_RESPONSE'), ensure_ascii=False, indent=2)}
```

| Check | Value |
|--|--|
| RAW_CATEGORY | cable |
| VALIDATED_CATEGORY | (empty) |
| RAW_CATEGORY_VALID_IN_REGISTRY | NO |
| VALIDATOR_REMOVED_CATEGORY | YES |
| VALIDATOR_CHANGED_SEMANTICS | YES (non-empty → empty) |
| empty_hypothesis_status | null (contract-invalid for empty hyps) |

### BUSINESS AFTER MODEL

No `procurement_ai_assessments` row linked for these SHADOW-only procurements in the Phase 8 dump (`assessments=0`).  
Therefore: no business_rule_result / medal / score applied for this SHADOW inference.  
Contextual prior additions: none observed on assessment row.

### FINAL UI

If this inference were production-authoritative, operator would see **empty MODEL_VALIDATED categories** (not `cable`).  
Inference is **SHADOW only** — not publication authority.

| Layer | 23591 |
|--|--|
| SOURCE | title storm-sewer equipment + OKPD plastic tanks |
| MODEL_VALIDATED | hypotheses=[] |
| BUSINESS_RULE | not applied (SHADOW; no assessment row) |
| PRESENTATION | would show empty model categories |

### ROOT CAUSE — CASE 23591

```
SOURCE_DATA_GAP=NO
MODEL_INPUT_GAP=NO
PYTHON_PREBIAS=NO
PROCUREMENT_FORM_ERROR=NO
OBJECT_CLASSIFICATION_ERROR=YES  # subtype CABLE vs storm-sewer equipment
ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR=YES
CATEGORY_MAPPING_ERROR=NO
INVALID_REGISTRY_CODE_GENERATION=YES
VALIDATOR_REJECTED_MODEL_CATEGORY=YES
ABSTENTION_ERROR=YES
OBJECT_PRIOR_OVERREACH=NO
POST_MODEL_BUSINESS_ERROR=NO
PRESENTATION_ERROR=NO
```

**CASE_23591_PRIMARY_ROOT_CAUSE=`ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR`**

Concise: model did not treat the purchase as storm-drainage equipment mapping to the visible registry code; it asserted a wrong product family (`cable` / later `equipment`). This is **not** a computers↔computer_components style taxonomy near-miss.

---

## COMPARE 37082 VS 23591

{md_table(out['compare_37082_vs_23591']['table'])}

**DO_37082_AND_23591_SHARE_THE_SAME_FAILURE_MECHANISM=`NO`**

Shared surface only: invalid RAW code → validator empty. Root mechanisms differ (mapping near-miss vs item-family misunderstanding).

---

## Corpus summary (n={out['TRACED_CASES']})

| Bucket | Count |
|--|--|
| DIRECT | {out['DIRECT_CASES']} |
| NEGATIVE | {out['NEGATIVE_CASES']} |
| OBJECT | {out['OBJECT_CASES']} |

Primary root-cause distribution:

{md_table([{'PRIMARY_ROOT_CAUSE': k, 'N': v} for k,v in sorted(out['failure_distribution'].items(), key=lambda x: -x[1])])}

Machine-readable: `model_decision_trace_cases.json`

### Focus companions

| Case | Expected | RAW | VALIDATED | Primary |
|--|--|--|--|--|
| 37082 | computers | computer_components | [] | CATEGORY_MAPPING_ERROR |
| 23591 | drainage_water_management | cable | [] | ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR |
| 27355 | empty | curbstone | curbstone | OBJECT_PRIOR_OVERREACH |
| 34517 | OBJECT_RELABELED | lighting | lighting | OBJECT_PRIOR_OVERREACH |

---

## PHASE_8 final block

See end of this WIP update in `REFACTORING_PLAN.md` / operator summary.
"""
    (REP / "MODEL_DECISION_TRACE_AUDIT.md").write_text(audit, encoding="utf-8")

    # INPUT FIELD AUDIT
    (REP / "MODEL_INPUT_FIELD_AUDIT.md").write_text(
        "# MODEL_INPUT_FIELD_AUDIT.md\n\n"
        "WIP: Phase 8 audit only. Fields not changed.\n\n"
        f"MODEL_INPUT_VERSION=`V3_ROUTING_MODEL_INPUT_V3`\n\n"
        + md_table(out["field_audit"])
        + "\n\n## Document boundary\n\n"
        + "\n".join(f"- **{k}**=`{v}`" for k, v in out["document_boundary"].items() if k != "FIELDS_ASKING_UNSEEN_DOCUMENTS")
        + "\n\nFields the prompt still asks that need unseen documents:\n\n"
        + "\n".join(f"- {x}" for x in out["document_boundary"]["FIELDS_ASKING_UNSEEN_DOCUMENTS"])
        + "\n",
        encoding="utf-8",
    )

    # QUESTION DECOMPOSITION
    (REP / "MODEL_QUESTION_DECOMPOSITION.md").write_text(
        "# MODEL_QUESTION_DECOMPOSITION.md\n\n"
        "WIP: Phase 8. Enumerated from production `prompt.py` (v5) and frozen SHADOW `prompt_v6_1.py`.\n\n"
        + md_table(
            [
                {
                    "QUESTION_ID": q["QUESTION_ID"],
                    "CLASS": q["CLASS"],
                    "OUTPUT_FIELD": q["OUTPUT_FIELD"],
                    "TAXONOMY": q["REQUIRES_COMMERCIAL_TAXONOMY"],
                    "DOCS": q["REQUIRES_DOCUMENT_CONTENT"],
                    "PRE_DOC_OK": q["CAN_BE_RELIABLY_ANSWERED_BEFORE_DOCUMENT_RESEARCH"],
                }
                for q in out["questions"]
            ]
        )
        + "\n\n## Plain-Russian questions\n\n"
        + "\n".join(f"### {q['QUESTION_ID']}\n{q['PLAIN_RUSSIAN_QUESTION']}\n" for q in out["questions"])
        + "\n## Critical semantic split\n\n"
        + "\n".join(f"- **{k}**=`{v}`" for k, v in out["semantic_split"].items())
        + "\n",
        encoding="utf-8",
    )

    # POSTPROCESSING PROVENANCE
    (REP / "MODEL_POSTPROCESSING_PROVENANCE.md").write_text(
        """# MODEL_POSTPROCESSING_PROVENANCE.md

WIP: Phase 8 audit only.

## Authority chain (unchanged)

| Stage | Store | May invent categories? |
|--|--|--|
| MODEL_RAW | `crm_v3_model_inference_runs.raw_model_json` | model only |
| MODEL_VALIDATED | `validated_model_result` | NO — filter/canonicalize only |
| BUSINESS_RULE | `business_rule_result` / scoring / medal | YES but must be attributed BUSINESS |
| CONTEXT_PRIOR | contextual_prior_hypotheses | PYTHON — never labeled MODEL |
| UI | projection layers | PRESENTATION only |

## Validator behavior (empirical Phase 8)

When RAW emits a non-registry `category_code`, validator drops the hypothesis.
It does **not** rewrite to the nearest valid code.
It does **not** set `empty_hypothesis_status` when the list becomes empty.
Result: many SHADOW empties are **validator wipes of invalid codes**, not true model abstention.

## Business after model (corpus)

Phase 8 dump found **0** `procurement_ai_assessments` rows for the traced SHADOW procurements.
Scores/medals/contextual merges were therefore **not** applied on these audit runs.

`MODEL_VALIDATED_MUTATED=NO`

## Python signals visible to model

| Signal | Visible? | Role |
|--|--|--|
| procurement_form_prior | YES | heuristic in prompt text |
| COMMERCIAL_PRODUCT_PRIORS | YES | inside model-input JSON |
| CONTEXTUAL_RESEARCH_PRIORS | YES | inside model-input JSON |
| OKPD priors list | YES | prompt JSON hints |
| title_hints | YES | subcategory exposure + registry compaction |
| DIRECT_CABLE_EXPECTED_RESULT | YES | model-input field |
| document names/text/evidence | NO | only counts |
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
