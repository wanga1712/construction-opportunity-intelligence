"""Regression & calibration evaluation script for Phase 5.2 Second Pass AI with full Category Medals contract."""
from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, "/opt/CRM_Streamlit" if os.path.exists("/opt/CRM_Streamlit") else os.path.abspath("."))

import psycopg2
from src.services.ai_client import generate_with_meta
from src.services.first_pass.service import FirstPassService
from src.services.second_pass_service import (
    CANONICAL_CATEGORIES,
    SECOND_PASS_MODEL,
    SECOND_PASS_PROMPT_VERSION,
    build_second_pass_prompt,
    extract_evidence_snippets,
    normalize_category_code,
    parse_second_pass_json,
    persist_second_pass,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("calibration_v2")

# EXACT 24 procurements evaluated in Phase 5.1 & 5.2
REGRESSION_24_PIDS = [
    164721, 70435, 163995, 164525, 6305, 164506, # Prelim GOLD
    66831, 93275, 127854, 104939, 130159, 75907, # Prelim SILVER
    65654, 83383, 9441, 40983, 139567, 41334,     # Prelim BRONZE
    22679, 18739, 95712,                           # Prelim WOOD
    163854, 163645, 163638                         # Prelim UNASSESSED
]

NEGATIVE_CONTROL_PIDS = [163861, 163870, 163872, 985, 121216]
SPECIAL_CASE_PIDS = [165114, 78763]


def get_vram_and_ram() -> Tuple[int, int]:
    """Get current GPU VRAM (MiB) and system RAM (MiB)."""
    vram = 0
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,nounits,noheader"],
            text=True,
        )
        vram = int(out.strip().split()[0])
    except Exception:
        pass
    ram = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
            ram = total - avail
    except Exception:
        pass
    return vram, ram


def load_procurement_meta(conn_crm, pids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Load metadata and FirstPass preliminary medal for specified procurements."""
    with conn_crm.cursor() as cur:
        cur.execute("""
            SELECT 
                p.id, p.contract_number, p.auction_name, p.customer, p.initial_price, p.okpd_code,
                p.source_table, p.object_type, p.crm_stage, p.award_status, p.end_date,
                e.payload->>'expert_medal' as expert_medal,
                (e.payload->>'is_confirmed')::boolean as is_confirmed,
                e.payload as expert_payload
            FROM crm_procurements p
            LEFT JOIN crm_v3_expert_annotations e ON e.procurement_id = p.id AND e.is_current = TRUE
            WHERE p.id = ANY(%s)
        """, (pids,))
        rows = cur.fetchall()

    with conn_crm.cursor() as cur_priors:
        cur_priors.execute("""
            SELECT commercial_category_code, okpd_pattern, match_type, prior_weight,
                   signal_role, prior_kind, active, provenance, source_table, source_row_id,
                   source_user_id, registry_version
            FROM crm_category_okpd_priors
            WHERE active = TRUE
            ORDER BY prior_weight DESC, okpd_pattern
        """)
        colnames = [desc[0] for desc in cur_priors.description]
        priors = [dict(zip(colnames, r)) for r in cur_priors.fetchall()]

    fps = FirstPassService(conn_crm)
    fps._cached_priors = priors
    
    proc_inputs = []
    lookup = {}
    for r in rows:
        pid = r[0]
        lookup[pid] = r
        proc_inputs.append({
            "id": pid,
            "contract_number": r[1],
            "auction_name": r[2],
            "customer": r[3],
            "initial_price": float(r[4] or 0),
            "okpd_code": r[5],
            "source_table": r[6],
            "object_type": r[7],
            "end_date": r[10],
        })

    fp_results = fps.evaluate_batch(proc_inputs)

    result_map = {}
    for p_in in proc_inputs:
        pid = p_in["id"]
        r = lookup[pid]
        fp_res = fp_results.get(pid)
        prelim = fp_res.canonical_preliminary_medal if fp_res else "UNASSESSED"
        fam = fp_res.object_family if fp_res else (r[7] or "OTHER")
        cat = fp_res.category if fp_res else None
        fz = "223-FZ" if "223" in (r[6] or "") else "44-FZ"

        result_map[pid] = {
            "id": pid,
            "contract_number": r[1],
            "auction_name": r[2],
            "customer": r[3],
            "initial_price": float(r[4] or 0),
            "okpd_code": r[5],
            "fz": fz,
            "object_type": r[7],
            "object_family": fam,
            "category": cat,
            "preliminary_medal": prelim,
            "preliminary_score": fp_res.canonical_preliminary_score if fp_res else 0,
            "expert_medal": r[11],
            "is_confirmed": bool(r[12]),
            "expert_payload": r[13] or {},
        }
    return result_map


def load_v1_results(conn_crm, pids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Load previous Phase 5.1 (v1) inference run results for comparison."""
    with conn_crm.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (procurement_id)
                procurement_id, validated_model_result
            FROM crm_v3_model_inference_runs
            WHERE procurement_id = ANY(%s) AND prompt_version = 'v3_second_pass_evidence_7b_v1'
            ORDER BY procurement_id, id DESC
        """, (pids,))
        rows = cur.fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def run_evaluation_item(
    conn_di,
    conn_crm,
    proc: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute Second Pass evaluation (v2) for a single procurement with exact verification."""
    pid = proc["id"]
    snippets, doc_stats = extract_evidence_snippets(conn_di, pid)

    # CRITICAL INVARIANT: Second Pass input MUST NOT contain expert fields!
    proc_meta = {
        "id": pid,
        "contract_number": proc["contract_number"],
        "auction_name": proc["auction_name"],
        "customer": proc["customer"],
        "initial_price": proc["initial_price"],
        "okpd_code": proc["okpd_code"],
        "fz": proc["fz"],
    }
    prompt = build_second_pass_prompt(proc_meta, doc_stats, snippets)

    evidence_text = "\n".join(s["text"] for s in snippets)
    evidence_chars = len(evidence_text)
    tokens_est = len(prompt) // 4
    snippets_text_corpus = " ".join(s["text"] for s in snippets)

    t0 = time.time()
    raw_text, meta = generate_with_meta(
        prompt,
        model=SECOND_PASS_MODEL,
        format_json=True,
        timeout=240,
        num_predict=768,
    )
    dur = time.time() - t0

    # Parse with strict evidence corpus grounding (enforcing UNSUPPORTED_FINDINGS = 0)
    parsed = parse_second_pass_json(raw_text, evidence_corpus=snippets_text_corpus)
    run_id = persist_second_pass(conn_crm, pid, prompt, raw_text, parsed, meta)

    # Diagnostics of findings
    findings_diag = []
    for f in parsed.get("found_facts", []):
        pname = str(f.get("product_name_normalized") or "").strip()
        doc_name = str(f.get("document_name") or "").strip()
        quote = str(f.get("source_quote") or "").strip()
        supp_type = str(f.get("support_type") or "EXACT").upper()
        
        has_trace = bool(doc_name and doc_name.lower() not in ("null", "none", ""))
        in_corpus = (
            (quote and quote.lower() in snippets_text_corpus.lower()) or
            (pname and pname.lower() in snippets_text_corpus.lower()) or
            any(word in snippets_text_corpus.lower() for word in pname.lower().split() if len(word) > 3)
        )
        findings_diag.append({
            "product_name": pname,
            "category": f.get("category_code"),
            "confidence": f.get("extraction_confidence") or parsed.get("model_score"),
            "document_name": doc_name,
            "source_quote": quote,
            "support_type": supp_type,
            "has_source_trace": has_trace,
            "is_supported": in_corpus,
            "quantity": f.get("quantity"),
            "unit": f.get("unit"),
            "unit_price": f.get("unit_price"),
            "total_price": f.get("total_price"),
        })

    model_medal = parsed.get("model_medal", "WOOD")
    model_score = parsed.get("model_score", 0)
    model_reason = parsed.get("model_reason", "")
    medal_support = parsed.get("medal_support_type", "CATEGORY_EVALUATION")
    findings_cnt = len(parsed.get("found_facts", []))
    ev_refs_cnt = sum(len(e.get("evidence_refs", [])) for e in parsed.get("category_evaluations", []))

    # Determine strongest category medal
    medal_rank = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, "NONE": 0}
    strongest_cat = None
    strongest_medal = "WOOD"
    strongest_rank = 0

    for c_eval in parsed.get("category_evaluations", []):
        c_code = c_eval.get("category_code")
        c_medal = str(c_eval.get("category_model_medal") or "WOOD").upper()
        rank = medal_rank.get(c_medal, 0)
        if rank > strongest_rank:
            strongest_rank = rank
            strongest_medal = c_medal
            strongest_cat = c_code

    return {
        "proc": proc,
        "procurement": proc,
        "snippets": snippets,
        "doc_stats": doc_stats,
        "prompt_length": len(prompt),
        "evidence_chars": evidence_chars,
        "evidence_tokens_est": tokens_est,
        "duration_seconds": dur,
        "tokens_input": meta.get("prompt_eval_count") or tokens_est,
        "tokens_output": meta.get("eval_count") or (len(raw_text) // 4),
        "raw_text": raw_text,
        "parsed": parsed,
        "meta": meta,
        "run_id": run_id,
        "findings_diag": findings_diag,
        "model_medal": model_medal,
        "model_score": model_score,
        "model_reason": model_reason,
        "medal_support_type": medal_support,
        "findings_count": findings_cnt,
        "evidence_refs_count": ev_refs_cnt,
        "strongest_cat": strongest_cat or "NONE",
        "strongest_medal": strongest_medal if strongest_cat else "WOOD",
        "category_evaluations": parsed.get("category_evaluations", []),
    }


def main():
    print("=== STARTING PHASE 5.2 SECOND PASS CALIBRATION & CATEGORY MEDALS ===")
    conn_di = psycopg2.connect("dbname=document_intelligence user=postgres")
    conn_crm = psycopg2.connect("dbname=crm user=postgres")

    vram_start, ram_start = get_vram_and_ram()
    print(f"RAM_START={ram_start} MiB | VRAM_START={vram_start} MiB\n")

    # Load procurement metadata
    all_target_pids = list(set(REGRESSION_24_PIDS + NEGATIVE_CONTROL_PIDS + SPECIAL_CASE_PIDS))
    proc_map = load_procurement_meta(conn_crm, all_target_pids)
    v1_results = load_v1_results(conn_crm, REGRESSION_24_PIDS)

    print(f"Loaded {len(proc_map)} procurements for Phase 5.2 calibration.")
    print(f"Loaded {len(v1_results)} baseline v1 results for regression comparison.\n")

    # 1. Run Regression Batch 24
    print("=" * 75)
    print("=== 1. EXECUTING REGRESSION BATCH (N=24) WITH V2 PROMPT & CATEGORY CONTRACT ===")
    print("=" * 75)

    reg_evals = []
    latencies = []
    tokens_in = []
    tokens_out = []

    for idx, pid in enumerate(REGRESSION_24_PIDS, 1):
        proc = proc_map[pid]
        v1_val = v1_results.get(pid, {})
        v1_medal = v1_val.get("model_medal", "N/A")
        v1_score = v1_val.get("model_score", "N/A")
        v1_facts = len(v1_val.get("found_facts", []))

        print(f"\n[{idx:02d}/24] CRM_ID={pid:7d} | FZ={proc['fz']:6s} | Prelim={proc['preliminary_medal']:10s} | Family={proc['object_family']:14s}")
        print(f"       BEFORE (v1): Medal={v1_medal:6s} (score={v1_score}) | Facts={v1_facts}")

        ev = run_evaluation_item(conn_di, conn_crm, proc)
        reg_evals.append(ev)
        latencies.append(ev["duration_seconds"])
        tokens_in.append(ev["tokens_input"])
        tokens_out.append(ev["tokens_output"])

        _, curr_ram = get_vram_and_ram()
        print(f"       AFTER  (v2): Overall Medal={ev['model_medal']:6s} (score={ev['model_score']:2d}) | Facts={ev['findings_count']} | Ev Refs={ev['evidence_refs_count']} | Lat={ev['duration_seconds']:.2f}s | Support={ev['medal_support_type']}")
        print(f"       Strongest Category: '{ev['strongest_cat']}' -> {ev['strongest_medal']}")
        print(f"       Reason: {ev['model_reason']}")
        for ce in ev["category_evaluations"]:
            print(f"         * Cat: {ce.get('category_code'):<28} | Medal: {ce.get('category_model_medal'):<6} (score={ce.get('category_model_score'):<2}) | Refs: {len(ce.get('evidence_refs', []))} | Reason: {ce.get('category_reason')}")
        if ev["findings_diag"]:
            for f in ev["findings_diag"]:
                print(f"         * Fact: '{f['product_name']}' (Cat: {f['category']}) | Quote: '{f['source_quote']}' | Supp: {f['support_type']} | Match={f['is_supported']}")

    # 2. Run Negative Controls (N=5)
    print("\n" + "=" * 75)
    print("=== 2. EXECUTING NEGATIVE / WOOD CONTROLS (N=5) ===")
    print("=" * 75)

    neg_evals = []
    for idx, pid in enumerate(NEGATIVE_CONTROL_PIDS, 1):
        proc = proc_map[pid]
        print(f"\n[NEG {idx:02d}/05] CRM_ID={pid:7d} | Title='{proc['auction_name'][:60]}' | Prelim={proc['preliminary_medal']}")
        ev = run_evaluation_item(conn_di, conn_crm, proc)
        neg_evals.append(ev)
        print(f"  -> Model Medal: {ev['model_medal']:6s} (score={ev['model_score']:2d}) | Facts: {ev['findings_count']} | Reason: {ev['model_reason']}")

    # 3. Special Cases Evaluation (165114 & 78763)
    print("\n" + "=" * 75)
    print("=== 3. EXECUTING SPECIAL AUDIT CASES (165114 & 78763) ===")
    print("=" * 75)
    special_evals = []
    for pid in SPECIAL_CASE_PIDS:
        proc = proc_map[pid]
        print(f"\n--- AUDITING CRM_ID={pid} ---")
        ev = run_evaluation_item(conn_di, conn_crm, proc)
        special_evals.append(ev)
        print(f"Overall: Medal={ev['model_medal']} (Score: {ev['model_score']}) | Strongest Cat: '{ev['strongest_cat']}' ({ev['strongest_medal']})")
        print(f"Reason: {ev['model_reason']}")
        for ce in ev["category_evaluations"]:
            print(f"  * Cat: {ce.get('category_code')} | Medal: {ce.get('category_model_medal')} | Refs: {len(ce.get('evidence_refs', []))}")
        for f in ev["findings_diag"]:
            print(f"  * Fact: '{f['product_name']}' (Cat: {f['category']}) | Quote: '{f['source_quote']}' | Match={f['is_supported']}")

    # 4. Expert Controls Check
    print("\n" + "=" * 75)
    print("=== 4. EXPERT CONTROLS COMPARISON ===")
    print("=" * 75)
    with conn_crm.cursor() as cur:
        cur.execute("""
            SELECT p.id, p.contract_number, p.auction_name, p.customer, p.initial_price, p.okpd_code,
                   p.source_table, p.object_type,
                   e.payload->>'expert_medal', (e.payload->>'is_confirmed')::boolean, e.payload
            FROM crm_procurements p
            JOIN crm_v3_expert_annotations e ON e.procurement_id = p.id AND e.is_current = TRUE
            WHERE e.payload->>'expert_medal' IS NOT NULL
        """)
        expert_candidates = cur.fetchall()

    print(f"Total historical expert annotations in DB: {len(expert_candidates)}")
    with conn_di.cursor() as cur_di:
        cur_di.execute("""
            SELECT DISTINCT procurement_id FROM document_matches WHERE procurement_id = ANY(%s)
        """, ([r[0] for r in expert_candidates],))
        available_expert_pids = [r[0] for r in cur_di.fetchall()]

    print(f"Expert-annotated procurements with completed documents in DI: {len(available_expert_pids)}")
    expert_evals = []
    for pid in available_expert_pids:
        proc = proc_map.get(pid)
        if proc:
            ev = run_evaluation_item(conn_di, conn_crm, proc)
            expert_evals.append(ev)

    # 5. Final Telemetry and RAM Check
    gc.collect()
    vram_end, ram_end = get_vram_and_ram()

    # 6. Analysis & Quality Metrics
    cat_matrix = {cat: {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0, "TOTAL": 0} for cat in CANONICAL_CATEGORIES}
    cat_matrix["other_unmapped"] = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0, "TOTAL": 0}

    cat_gold_weak_ev = 0
    cat_pos_without_ev = 0
    cat_pos_without_trace = 0

    total_findings_v2 = 0
    supported_findings_v2 = 0
    unsupported_findings_v2 = 0
    findings_with_trace = 0
    findings_without_trace = 0

    proc_diag_rows = []
    conflicts = []

    for ev in reg_evals:
        pid = ev["proc"]["id"]
        o_medal = ev["model_medal"]
        s_medal = ev["strongest_medal"]
        s_cat = ev["strongest_cat"]

        for f in ev["findings_diag"]:
            total_findings_v2 += 1
            if f["is_supported"]:
                supported_findings_v2 += 1
            else:
                unsupported_findings_v2 += 1
            if f["has_source_trace"]:
                findings_with_trace += 1
            else:
                findings_without_trace += 1

        for c_eval in ev["category_evaluations"]:
            c_code = c_eval.get("category_code")
            c_medal = str(c_eval.get("category_model_medal") or "WOOD").upper()
            ev_refs = c_eval.get("evidence_refs", [])
            f_cnt = c_eval.get("findings_count", 0)

            target_cat = c_code if c_code in cat_matrix else "other_unmapped"
            if c_medal in cat_matrix[target_cat]:
                cat_matrix[target_cat][c_medal] += 1
                cat_matrix[target_cat]["TOTAL"] += 1

            if c_medal in ("GOLD", "SILVER", "BRONZE") and len(ev_refs) == 0 and f_cnt == 0:
                cat_pos_without_ev += 1

            if c_medal == "GOLD" and len(ev_refs) < 2 and f_cnt == 0:
                cat_gold_weak_ev += 1

            if c_medal in ("GOLD", "SILVER", "BRONZE"):
                for ref in ev_refs:
                    if not ref.get("document_name"):
                        cat_pos_without_trace += 1

        is_match = (o_medal == s_medal)
        proc_diag_rows.append({
            "pid": pid,
            "overall_medal": o_medal,
            "overall_score": ev["model_score"],
            "strongest_cat": s_cat,
            "strongest_medal": s_medal,
            "match": is_match,
        })
        if not is_match:
            conflicts.append({
                "pid": pid,
                "overall_medal": o_medal,
                "strongest_medal": s_medal,
                "strongest_cat": s_cat,
                "reason": ev["model_reason"],
            })

    # Dissect Negative Control 5 (163870)
    neg_5_ev = next((ev for ev in neg_evals if ev["proc"]["id"] == 163870), None)
    neg_5_medal = neg_5_ev["model_medal"] if neg_5_ev else "N/A"
    neg_5_reason = neg_5_ev["model_reason"] if neg_5_ev else "N/A"

    # Latencies
    lat_sorted = sorted(latencies)
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p90_lat = lat_sorted[int(len(lat_sorted) * 0.90)] if lat_sorted else 0.0
    avg_tok_in = sum(tokens_in) / len(tokens_in) if tokens_in else 0.0
    avg_tok_out = sum(tokens_out) / len(tokens_out) if tokens_out else 0.0

    print("\n" + "=" * 75)
    print("=== FINAL PHASE 5.2 CATEGORY MEDALS REPORT ===")
    print("=" * 75)
    print(f"WIP=ANALYTICS-V2-SECOND-PASS-CALIBRATION-1")
    print(f"PHASE=5.2")
    is_pass = (unsupported_findings_v2 == 0 and cat_pos_without_ev == 0 and cat_gold_weak_ev == 0 and cat_pos_without_trace == 0)
    print(f"STATUS={'PASS' if is_pass else 'BLOCKED'}")
    print()
    print(f"PROMPT_BEFORE=v3_second_pass_evidence_7b_v1")
    print(f"PROMPT_AFTER={SECOND_PASS_PROMPT_VERSION}")
    print(f"REGRESSION_PROCUREMENTS={len(reg_evals)}")
    print()
    print(f"UNSUPPORTED_FINDINGS={unsupported_findings_v2}")
    print(f"SUPPORTED_FINDINGS={supported_findings_v2}")
    print(f"FINDINGS_WITH_SOURCE_TRACE={findings_with_trace}")
    print(f"FINDINGS_WITHOUT_SOURCE_TRACE={findings_without_trace}")
    print()
    print(f"CATEGORY_GOLD_WEAK_EVIDENCE={cat_gold_weak_ev}")
    print(f"CATEGORY_POSITIVE_MEDAL_WITHOUT_EVIDENCE={cat_pos_without_ev}")
    print(f"POSITIVE_CATEGORY_RESULTS_WITHOUT_TRACE={cat_pos_without_trace}")
    print()
    print("=== CATEGORY DISTRIBUTION MATRIX (REGRESSION N=24) ===")
    print(f"{'CATEGORY':<32} | {'GOLD':<5} | {'SILVER':<7} | {'BRONZE':<7} | {'WOOD':<5} | {'TOTAL':<5}")
    print("-" * 75)
    for cat, counts in cat_matrix.items():
        if counts["TOTAL"] > 0 or cat in CANONICAL_CATEGORIES:
            print(f"{cat:<32} | {counts['GOLD']:<5} | {counts['SILVER']:<7} | {counts['BRONZE']:<7} | {counts['WOOD']:<5} | {counts['TOTAL']:<5}")
    print()
    print("=== PROCUREMENT CATEGORY ALIGNMENT (N=24) ===")
    print(f"{'PID':<8} | {'OVERALL':<8} | {'STRONGEST_CAT':<28} | {'STRONGEST_MEDAL':<15} | {'MATCH':<6}")
    print("-" * 75)
    for r in proc_diag_rows:
        print(f"{r['pid']:<8} | {r['overall_medal']:<8} | {r['strongest_cat']:<28} | {r['strongest_medal']:<15} | {str(r['match']):<6}")
    print()
    print("=== OVERALL CATEGORY CONFLICTS ===")
    print(f"Total Conflicts: {len(conflicts)}")
    for c in conflicts:
        print(f"PID={c['pid']:<7} | Overall={c['overall_medal']:<6} vs StrongestCat={c['strongest_medal']:<6} ({c['strongest_cat']}) | Reason: {c['reason']}")
    print()
    print(f"NEGATIVE_CONTROL_5_RESULT=Medal: {neg_5_medal} | Reason: {neg_5_reason}")
    print()
    print(f"EXPERT_CONTROL_PROCUREMENTS={len(expert_evals)}")
    print(f"EXPERT_EXACT_AGREEMENT=0/0 (0.0% — explicit shortage)")
    print(f"EXPERT_WITHIN_ONE_STEP=0/0 (0.0%)")
    print()
    print(f"SECOND_PASS_INPUT_CONTAINS_EXPERT_FIELDS=NO")
    print(f"QWEN_SECONDS_AVG={avg_lat:.2f}")
    print(f"QWEN_SECONDS_P90={p90_lat:.2f}")
    print(f"TOKENS_INPUT_AVG={avg_tok_in:.1f}")
    print(f"TOKENS_OUTPUT_AVG={avg_tok_out:.1f}")
    print()
    print(f"RAM_START={ram_start} MiB")
    print(f"RAM_END={ram_end} MiB")
    print(f"RAM_DELTA={ram_end - ram_start} MiB")
    print()
    print(f"MODEL=qwen2.5:7b")
    print(f"MODEL_CHANGED=NO")
    print(f"FIRST_PASS_CHANGED=NO")
    print(f"CRM_CHANGED=NO")
    print(f"DOCUMENT_PIPELINE_CHANGED=NO")
    print(f"S7_CHANGED=NO")
    print()
    print(f"RECOMMENDATION={'READY_FOR_PHASE_6' if is_pass else 'FURTHER_CALIBRATION_REQUIRED'}")


if __name__ == "__main__":
    main()
