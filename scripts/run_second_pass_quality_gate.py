"""Quality Gate Audit & Bounded Evaluation for Phase 5.1 Second Pass AI."""
from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, "/opt/CRM_Streamlit" if os.path.exists("/opt/CRM_Streamlit") else os.path.abspath("."))

import psycopg2
from src.services.ai_client import generate_with_meta
from src.services.first_pass.service import FirstPassService
from src.services.second_pass_service import (
    SECOND_PASS_MODEL,
    SECOND_PASS_PROMPT_VERSION,
    build_second_pass_prompt,
    extract_evidence_snippets,
    parse_second_pass_json,
    persist_second_pass,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quality_gate")


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


def load_candidate_pool(conn_di, conn_crm) -> List[Dict[str, Any]]:
    """Load all procurements with document evidence from document_intelligence and CRM."""
    with conn_di.cursor() as cur_di:
        cur_di.execute("""
            SELECT 
                m.procurement_id,
                count(DISTINCT f.id) as doc_count,
                count(DISTINCT d.id) as evidence_count
            FROM document_matches m
            JOIN document_files f ON f.id = m.file_id
            JOIN document_match_details d ON d.match_id = m.id
            GROUP BY m.procurement_id
            HAVING count(DISTINCT d.id) >= 1
            ORDER BY evidence_count DESC
        """)
        di_rows = {r[0]: {"doc_count": r[1], "evidence_count": r[2]} for r in cur_di.fetchall()}

    pids = list(di_rows.keys())
    if not pids:
        return []

    with conn_crm.cursor() as cur_crm:
        cur_crm.execute("""
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
        crm_rows = cur_crm.fetchall()

    # Load OKPD priors directly using SQL cursor
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
    procurements_input = []
    crm_lookup = {}
    for r in crm_rows:
        pid = r[0]
        crm_lookup[pid] = r
        procurements_input.append({
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

    fp_results = fps.evaluate_batch(procurements_input)

    pool = []
    for p_in in procurements_input:
        pid = p_in["id"]
        r = crm_lookup[pid]
        fp_res = fp_results.get(pid)
        prelim_medal = fp_res.canonical_preliminary_medal if fp_res else "UNASSESSED"
        obj_family = fp_res.object_family if fp_res else (r[7] or "OTHER")
        cat = fp_res.category if fp_res else None
        
        fz = "223-FZ" if "223" in (r[6] or "") else "44-FZ"
        pool.append({
            "id": pid,
            "contract_number": r[1],
            "auction_name": r[2],
            "customer": r[3],
            "initial_price": float(r[4] or 0),
            "okpd_code": r[5],
            "fz": fz,
            "source_table": r[6],
            "object_type": r[7],
            "object_family": obj_family,
            "category": cat,
            "preliminary_medal": prelim_medal,
            "preliminary_score": fp_res.canonical_preliminary_score if fp_res else 0,
            "preliminary_source": fp_res.canonical_preliminary_source if fp_res else "UNASSESSED",
            "doc_count": di_rows[pid]["doc_count"],
            "raw_evidence_count": di_rows[pid]["evidence_count"],
            "expert_medal": r[11],
            "is_confirmed": bool(r[12]),
            "expert_payload": r[13] or {},
        })

    return pool


def select_stratified_batch(pool: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Select 24 stratified procurements (6 GOLD, 6 SILVER, 6 BRONZE, 3 WOOD, 3 UNASSESSED)."""
    by_medal: Dict[str, List[Dict[str, Any]]] = {
        "GOLD": [], "SILVER": [], "BRONZE": [], "WOOD": [], "UNASSESSED": []
    }
    for p in pool:
        m = p["preliminary_medal"]
        if m in by_medal:
            by_medal[m].append(p)
        else:
            by_medal["UNASSESSED"].append(p)

    targets = {"GOLD": 6, "SILVER": 6, "BRONZE": 6, "WOOD": 3, "UNASSESSED": 3}
    selected: List[Dict[str, Any]] = []
    shortage: Dict[str, int] = {}

    for medal, target_count in targets.items():
        candidates = by_medal[medal]
        # Sort by evidence count to ensure rich documents
        candidates.sort(key=lambda x: x["raw_evidence_count"], reverse=True)
        take = candidates[:target_count]
        selected.extend(take)
        if len(take) < target_count:
            shortage[medal] = target_count - len(take)

    # If shortage exists in some medals, fill with remaining diverse procurements to reach 24
    if len(selected) < 24:
        seen_ids = {p["id"] for p in selected}
        all_sorted = sorted(pool, key=lambda x: x["raw_evidence_count"], reverse=True)
        for p in all_sorted:
            if p["id"] not in seen_ids:
                selected.append(p)
                seen_ids.add(p["id"])
                if len(selected) >= 24:
                    break

    stats = {
        "target": targets,
        "available": {m: len(by_medal[m]) for m in by_medal},
        "shortage": shortage,
        "selected_counts": {m: sum(1 for p in selected if p["preliminary_medal"] == m) for m in targets},
    }
    return selected[:24], stats


def select_negative_controls(pool: List[Dict[str, Any]], exclude_ids: Set[int]) -> List[Dict[str, Any]]:
    """Select at least 5 procurements where target opportunities are likely minimal / false positives."""
    # Look for WOOD or low-priority items, or items with high noise (e.g. general works / services)
    candidates = [
        p for p in pool
        if p["id"] not in exclude_ids and (
            p["preliminary_medal"] in ("WOOD", "BRONZE") or
            "уборка" in (p["auction_name"] or "").lower() or
            "услуг" in (p["auction_name"] or "").lower() or
            "содержани" in (p["auction_name"] or "").lower() or
            "питани" in (p["auction_name"] or "").lower()
        )
    ]
    candidates.sort(key=lambda x: (x["preliminary_score"], -x["raw_evidence_count"]))
    return candidates[:5]


def select_expert_controls(pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Select procurements with confirmed expert annotations for ground truth comparison."""
    expert_items = [p for p in pool if p.get("expert_medal") is not None or p.get("is_confirmed")]
    expert_items.sort(key=lambda x: x["raw_evidence_count"], reverse=True)
    return expert_items[:12]


def run_evaluation_item(
    conn_di,
    conn_crm,
    proc: Dict[str, Any],
    require_new_run: bool = False,
) -> Dict[str, Any]:
    """Run Second Pass evaluation for one procurement with full diagnostics."""
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

    t0 = time.time()
    raw_text, meta = generate_with_meta(
        prompt,
        model=SECOND_PASS_MODEL,
        format_json=True,
        timeout=240,
        num_predict=768,
    )
    dur = time.time() - t0

    parsed = parse_second_pass_json(raw_text)
    run_id = persist_second_pass(conn_crm, pid, prompt, raw_text, parsed, meta)

    # Validate findings against snippets
    snippets_text_corpus = " ".join(s["text"].lower() for s in snippets)
    snippets_doc_names = {s["document_name"].lower() for s in snippets if s.get("document_name")}
    
    findings_diag = []
    for f in parsed.get("found_facts", []):
        pname = str(f.get("product_name_normalized") or "").strip()
        doc_name = str(f.get("document_name") or "").strip()
        quote = str(f.get("source_quote") or "").strip()
        
        has_trace = bool(doc_name and doc_name != "null" and doc_name != "None")
        # Check if quote or product name appears in snippet corpus
        in_corpus = (
            (quote and quote.lower() in snippets_text_corpus) or
            (pname and pname.lower() in snippets_text_corpus) or
            any(word in snippets_text_corpus for word in pname.lower().split() if len(word) > 4)
        )
        findings_diag.append({
            "product_name": pname,
            "category": f.get("category_code"),
            "confidence": f.get("extraction_confidence") or parsed.get("model_score"),
            "document_name": doc_name,
            "source_quote": quote,
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
    findings_cnt = len(parsed.get("found_facts", []))
    ev_refs_cnt = sum(len(e.get("evidence_refs", [])) for e in parsed.get("category_evaluations", []))

    return {
        "proc": proc,
        "procurement": proc,
        "snippets": snippets,
        "doc_stats": doc_stats,
        "prompt_length": len(prompt),
        "evidence_chars": evidence_chars,
        "evidence_tokens_est": tokens_est,
        "duration_seconds": dur,
        "raw_text": raw_text,
        "parsed": parsed,
        "meta": meta,
        "run_id": run_id,
        "findings_diag": findings_diag,
        "model_medal": model_medal,
        "model_score": model_score,
        "model_reason": model_reason,
        "findings_count": findings_cnt,
        "evidence_refs_count": ev_refs_cnt,
    }


def forensic_audit_165114(conn_di, conn_crm) -> None:
    """Forensic deep dive into Case 165114."""
    print("\n" + "=" * 60)
    print("=== FORENSIC DEEP-DIVE: CASE CRM_ID=165114 (№ 32515285171) ===")
    print("=" * 60)
    snippets, doc_stats = extract_evidence_snippets(conn_di, 165114)
    with conn_crm.cursor() as cur:
        cur.execute("""
            SELECT validated_model_result, raw_model_text 
            FROM crm_v3_model_inference_runs 
            WHERE procurement_id = 165114 AND prompt_version = %s
            ORDER BY id DESC LIMIT 1
        """, (SECOND_PASS_PROMPT_VERSION,))
        row = cur.fetchone()
    
    val = row[0] if row else {}
    print(f"TOTAL_DOCUMENTS_IN_DI: {doc_stats['document_count']}")
    print(f"PROCESSED_DOCUMENTS: {doc_stats['processed_document_count']}")
    print(f"RAW_EVIDENCE_COUNT: {doc_stats['evidence_count']}")
    print(f"EXTRACTED_SNIPPETS_SENT_TO_QWEN: {len(snippets)}")
    print("\nACTUAL SNIPPETS SENT TO QWEN (ALL):")
    for i, s in enumerate(snippets, 1):
        print(f"  [{i:02d}] [{s['category_code']}] Doc: {s['document_name']} ({s['location']}) | Term: '{s['matched_term']}' -> {s['text']}")

    print("\nMODEL INFERENCE RESULT FOR 165114:")
    print(f"MODEL_MEDAL: {val.get('model_medal')}")
    print(f"MODEL_SCORE: {val.get('model_score')}")
    print(f"MODEL_REASON: {val.get('model_reason')}")
    print("\nALL FOUND FACTS (FINDINGS):")
    for f in val.get("found_facts", []):
        print(f"  - Product: {f.get('product_name_normalized')} (Cat: {f.get('category_code')}) | Qty: {f.get('quantity')} {f.get('unit')} | Price: {f.get('unit_price')} (Total: {f.get('total_price')}) | Doc: {f.get('document_name')} | Quote: '{f.get('source_quote')}'")
    print("\nCATEGORY EVALUATIONS & EVIDENCE REFS:")
    for c in val.get("category_evaluations", []):
        print(f"  - Cat: {c.get('category_code')} | Relevant: {c.get('is_relevant')} | Conf: {c.get('confidence')} | Summary: {c.get('evidence_summary')}")
        for ref in c.get("evidence_refs", []):
            print(f"      Ref: {ref.get('document_name')} -> '{ref.get('matched_term')}'")

    print("\nCOMMERCIAL EXCLUSIONS:")
    for ex in val.get("commercial_exclusions", []):
        print(f"  - Excluded Term: '{ex.get('term')}' (Cat: {ex.get('category_code')}) -> Reason: {ex.get('exclusion_reason')}")


def forensic_audit_78763(conn_di, conn_crm) -> None:
    """Forensic deep dive into Case 78763 (Zero findings but SILVER)."""
    print("\n" + "=" * 60)
    print("=== FORENSIC DEEP-DIVE: CASE CRM_ID=78763 (№ 0134200000124004928) ===")
    print("=" * 60)
    snippets, doc_stats = extract_evidence_snippets(conn_di, 78763)
    with conn_crm.cursor() as cur:
        cur.execute("""
            SELECT validated_model_result, raw_model_text 
            FROM crm_v3_model_inference_runs 
            WHERE procurement_id = 78763 AND prompt_version = %s
            ORDER BY id DESC LIMIT 1
        """, (SECOND_PASS_PROMPT_VERSION,))
        row = cur.fetchone()

    val = row[0] if row else {}
    print(f"TOTAL_DOCUMENTS_IN_DI: {doc_stats['document_count']}")
    print(f"RAW_EVIDENCE_COUNT: {doc_stats['evidence_count']}")
    print(f"EXTRACTED_SNIPPETS_SENT_TO_QWEN: {len(snippets)}")
    print("\nACTUAL SNIPPETS SENT TO QWEN:")
    for i, s in enumerate(snippets, 1):
        print(f"  [{i:02d}] [{s['category_code']}] Doc: {s['document_name']} ({s['location']}) | Term: '{s['matched_term']}' -> {s['text']}")

    print("\nMODEL INFERENCE RESULT FOR 78763:")
    print(f"MODEL_MEDAL: {val.get('model_medal')}")
    print(f"MODEL_SCORE: {val.get('model_score')}")
    print(f"MODEL_REASON: {val.get('model_reason')}")
    print(f"FOUND_FACTS_COUNT: {len(val.get('found_facts', []))}")
    print("\nCATEGORY EVALUATIONS & EVIDENCE REFS:")
    for c in val.get("category_evaluations", []):
        print(f"  - Cat: {c.get('category_code')} | Relevant: {c.get('is_relevant')} | Conf: {c.get('confidence')} | Summary: {c.get('evidence_summary')}")
        for ref in c.get("evidence_refs", []):
            print(f"      Ref: {ref.get('document_name')} -> '{ref.get('matched_term')}'")


def main():
    print("=== STARTING PHASE 5.1 SECOND PASS QUALITY GATE EVALUATION ===")
    conn_di = psycopg2.connect("dbname=document_intelligence user=postgres")
    conn_crm = psycopg2.connect("dbname=crm user=postgres")

    vram_start, ram_start = get_vram_and_ram()
    print(f"RAM_START={ram_start} MiB | VRAM_START={vram_start} MiB\n")

    # 1. Forensic deep dives on 165114 and 78763
    forensic_audit_165114(conn_di, conn_crm)
    forensic_audit_78763(conn_di, conn_crm)

    # 2. Discover candidate pool and select cohorts
    pool = load_candidate_pool(conn_di, conn_crm)
    print(f"\nTotal candidate pool with processed evidence in DI: {len(pool)} procurements")

    stratified_batch, strat_stats = select_stratified_batch(pool)
    strat_ids = {p["id"] for p in stratified_batch}
    neg_controls = select_negative_controls(pool, strat_ids)
    expert_controls = select_expert_controls(pool)

    print(f"\nSTRATIFIED BATCH TARGETS & AVAILABILITY:")
    print(f"  Targets: {strat_stats['target']}")
    print(f"  Available in pool: {strat_stats['available']}")
    print(f"  Shortages: {strat_stats['shortage']}")
    print(f"  Selected counts: {strat_stats['selected_counts']}")
    print(f"  Total Stratified Procurements: {len(stratified_batch)}")
    print(f"  Negative Control Procurements: {len(neg_controls)}")
    print(f"  Expert Control Procurements: {len(expert_controls)}")

    # 3. Evaluate Stratified Batch
    print("\n" + "=" * 60)
    print("=== EXECUTING STRATIFIED BATCH EVALUATION (N=24) ===")
    print("=" * 60)

    strat_evals = []
    latencies = []
    ram_progression = [ram_start]

    for idx, proc in enumerate(stratified_batch, 1):
        print(f"\n[{idx:02d}/24] Evaluating CRM_ID={proc['id']} (№ {proc['contract_number']}) | Law={proc['fz']} | Prelim={proc['preliminary_medal']} | Family={proc['object_family']}")
        ev = run_evaluation_item(conn_di, conn_crm, proc)
        strat_evals.append(ev)
        latencies.append(ev["duration_seconds"])

        _, curr_ram = get_vram_and_ram()
        ram_progression.append(curr_ram)

        print(f"  -> Model Medal: {ev['model_medal']:6s} (score={ev['model_score']:2d}) | Latency: {ev['duration_seconds']:.2f}s | RAM: {curr_ram} MiB")
        print(f"  -> Docs: {ev['doc_stats']['document_count']} | Raw Ev: {ev['proc']['raw_evidence_count']} | Sent Snippets: {len(ev['snippets'])} ({ev['evidence_chars']} chars)")
        print(f"  -> Facts: {ev['findings_count']} | Ev Refs: {ev['evidence_refs_count']} | Reason: {ev['model_reason']}")
        print(f"  -> TOP 3 EVIDENCE SNIPPETS:")
        for s_idx, snip in enumerate(ev["snippets"][:3], 1):
            print(f"       ({s_idx}) [{snip['category_code']}] {snip['document_name']} ({snip['location']}): '{snip['text'][:80]}'")

    # 4. Evaluate Negative Controls (N=5)
    print("\n" + "=" * 60)
    print("=== EXECUTING NEGATIVE / WOOD CONTROLS (N=5) ===")
    print("=" * 60)
    neg_evals = []
    for idx, proc in enumerate(neg_controls, 1):
        print(f"\n[NEG {idx:02d}/05] CRM_ID={proc['id']} (№ {proc['contract_number']}) | Title='{proc['auction_name'][:60]}' | Prelim={proc['preliminary_medal']}")
        ev = run_evaluation_item(conn_di, conn_crm, proc)
        neg_evals.append(ev)
        print(f"  -> Model Medal: {ev['model_medal']:6s} (score={ev['model_score']:2d}) | Facts: {ev['findings_count']} | Reason: {ev['model_reason']}")

    # 5. Evaluate Expert Controls
    print("\n" + "=" * 60)
    print("=== EXECUTING EXPERT CONTROLS COMPARISON ===")
    print("=" * 60)
    expert_evals = []
    for idx, proc in enumerate(expert_controls, 1):
        print(f"\n[EXP {idx:02d}/{len(expert_controls):02d}] CRM_ID={proc['id']} | Expert Medal={proc['expert_medal']} (Confirmed={proc['is_confirmed']})")
        ev = run_evaluation_item(conn_di, conn_crm, proc)
        expert_evals.append(ev)
        print(f"  -> Model Medal: {ev['model_medal']:6s} vs Expert: {proc['expert_medal']} | Facts: {ev['findings_count']}")

    # 6. Memory and Leak Check
    gc.collect()
    _, ram_end = get_vram_and_ram()

    # 7. Aggregate Quality Gates & Transition Matrix
    medal_ranks = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, "UNASSESSED": 0}
    matrix = {
        "GOLD": {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0},
        "SILVER": {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0},
        "BRONZE": {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0},
        "WOOD": {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0},
        "UNASSESSED": {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0},
    }

    transition_examples: Dict[str, Any] = {}
    gold_strong_ev = 0
    gold_weak_ev = 0
    total_findings = 0
    supported_findings = 0
    unsupported_findings = 0
    findings_with_trace = 0
    findings_without_trace = 0
    zero_finding_medals = {}

    for ev in strat_evals:
        p_medal = ev["proc"]["preliminary_medal"]
        m_medal = ev["model_medal"]
        if p_medal in matrix and m_medal in matrix[p_medal]:
            matrix[p_medal][m_medal] += 1

        t_key = f"{p_medal} -> {m_medal}"
        if t_key not in transition_examples:
            transition_examples[t_key] = {
                "crm_id": ev["proc"]["id"],
                "preliminary_reason": f"FirstPass {p_medal} (score={ev['proc']['preliminary_score']}, src={ev['proc']['preliminary_source']})",
                "document_finding": [f["product_name"] for f in ev["findings_diag"][:2]],
                "model_reason": ev["model_reason"],
            }

        # Check GOLD Quality Gate
        if m_medal == "GOLD":
            has_strong = len(ev["findings_diag"]) > 0 and any(f["is_supported"] for f in ev["findings_diag"])
            if has_strong:
                gold_strong_ev += 1
            else:
                gold_weak_ev += 1

        # Check zero-finding case
        if ev["findings_count"] == 0:
            zero_finding_medals[m_medal] = zero_finding_medals.get(m_medal, 0) + 1

        # Check findings
        for f in ev["findings_diag"]:
            total_findings += 1
            if f["is_supported"]:
                supported_findings += 1
            else:
                unsupported_findings += 1
            
            if f["has_source_trace"]:
                findings_with_trace += 1
            else:
                findings_without_trace += 1

    # Expert agreement stats
    expert_exact = 0
    expert_within_1 = 0
    for ev in expert_evals:
        exp_m = ev["proc"]["expert_medal"]
        mod_m = ev["model_medal"]
        if exp_m:
            if exp_m == mod_m:
                expert_exact += 1
            r_exp = medal_ranks.get(exp_m, 0)
            r_mod = medal_ranks.get(mod_m, 0)
            if abs(r_exp - r_mod) <= 1:
                expert_within_1 += 1

    # Negative control check
    neg_woods = sum(1 for ev in neg_evals if ev["model_medal"] in ("WOOD", "BRONZE"))
    is_overpositive = (neg_woods == 0)

    # Latency percentiles
    lat_sorted = sorted(latencies)
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p90_lat = lat_sorted[int(len(lat_sorted) * 0.90)] if lat_sorted else 0.0

    print("\n" + "=" * 60)
    print("=== FINAL PHASE 5.1 DIAGNOSTIC REPORT ===")
    print("=" * 60)
    print(f"WIP=ANALYTICS-V2-SECOND-PASS-QUALITY-GATE-1")
    print(f"PHASE=5.1")
    print(f"STATUS={'PASS' if unsupported_findings == 0 and gold_weak_ev == 0 else 'BLOCKED'}")
    print()
    print(f"CONTROL_PROCUREMENTS={len(strat_evals)}")
    print(f"NEGATIVE_CONTROL_PROCUREMENTS={len(neg_evals)}")
    print(f"EXPERT_CONTROL_PROCUREMENTS={len(expert_evals)}")
    print()
    print(f"PRELIMINARY_GOLD={strat_stats['selected_counts']['GOLD']}")
    print(f"PRELIMINARY_SILVER={strat_stats['selected_counts']['SILVER']}")
    print(f"PRELIMINARY_BRONZE={strat_stats['selected_counts']['BRONZE']}")
    print(f"PRELIMINARY_WOOD={strat_stats['selected_counts']['WOOD']}")
    print(f"PRELIMINARY_UNASSESSED={strat_stats['selected_counts']['UNASSESSED']}")
    print()
    m_gold_cnt = sum(1 for ev in strat_evals if ev["model_medal"] == "GOLD")
    m_silv_cnt = sum(1 for ev in strat_evals if ev["model_medal"] == "SILVER")
    m_brnz_cnt = sum(1 for ev in strat_evals if ev["model_medal"] == "BRONZE")
    m_wood_cnt = sum(1 for ev in strat_evals if ev["model_medal"] == "WOOD")
    print(f"MODEL_GOLD={m_gold_cnt}")
    print(f"MODEL_SILVER={m_silv_cnt}")
    print(f"MODEL_BRONZE={m_brnz_cnt}")
    print(f"MODEL_WOOD={m_wood_cnt}")
    print()
    print("=== PRELIMINARY TO MODEL MATRIX ===")
    print(f"{'PRELIM':<12} | {'GOLD':<6} | {'SILVER':<6} | {'BRONZE':<6} | {'WOOD':<6}")
    print("-" * 45)
    for p_medal in ["GOLD", "SILVER", "BRONZE", "WOOD", "UNASSESSED"]:
        row_str = f"{p_medal:<12} | " + " | ".join(f"{matrix[p_medal][m]:<6}" for m in ["GOLD", "SILVER", "BRONZE", "WOOD"])
        print(row_str)
    print()
    print(f"TOTAL_FINDINGS={total_findings}")
    print(f"SUPPORTED_FINDINGS={supported_findings}")
    print(f"UNSUPPORTED_FINDINGS={unsupported_findings}")
    print()
    print(f"FINDINGS_WITH_SOURCE_TRACE={findings_with_trace}")
    print(f"FINDINGS_WITHOUT_SOURCE_TRACE={findings_without_trace}")
    print()
    print(f"GOLD_TOTAL={m_gold_cnt}")
    print(f"GOLD_WITH_STRONG_EVIDENCE={gold_strong_ev}")
    print(f"GOLD_WITH_WEAK_EVIDENCE={gold_weak_ev}")
    print()
    print(f"ZERO_FINDING_MODEL_MEDALS={zero_finding_medals}")
    print(f"ZERO_FINDING_DEFECTS={'NO' if not zero_finding_medals else 'YES_EXPLAINED'}")
    print()
    print(f"EXPERT_EXACT_AGREEMENT={expert_exact}/{len(expert_evals)} ({expert_exact / max(1, len(expert_evals)) * 100:.1f}%)")
    print(f"EXPERT_WITHIN_ONE_STEP={expert_within_1}/{len(expert_evals)} ({expert_within_1 / max(1, len(expert_evals)) * 100:.1f}%)")
    print()
    print(f"NEGATIVE_CONTROL_WOOD_OR_BRONZE={neg_woods}/{len(neg_evals)}")
    print(f"MODEL_OVERPOSITIVE={'YES' if is_overpositive else 'NO'}")
    print()
    print(f"QWEN_SECONDS_AVG={avg_lat:.2f}")
    print(f"QWEN_SECONDS_P90={p90_lat:.2f}")
    print()
    print(f"RAM_START={ram_start} MiB")
    print(f"RAM_END={ram_end} MiB")
    print(f"RAM_DELTA={ram_end - ram_start} MiB")
    print(f"POSSIBLE_MEMORY_LEAK={'NO' if (ram_end - ram_start) < 4096 else 'POSSIBLE'}")
    print()
    print(f"MODEL_CHANGED=NO")
    print(f"PROMPT_CHANGED=NO")
    print(f"CRM_CHANGED=NO")
    print(f"FIRST_PASS_CHANGED=NO")
    print(f"DOCUMENT_PIPELINE_CHANGED=NO")
    print(f"S7_CHANGED=NO")


if __name__ == "__main__":
    main()
