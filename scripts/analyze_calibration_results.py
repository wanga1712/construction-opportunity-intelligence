"""Extract detailed Phase 5.2 category matrices and reports from database."""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, List

import psycopg2
from psycopg2.extras import RealDictCursor

# EXACT 24 procurements evaluated in Phase 5.1 & 5.2
REGRESSION_24_PIDS = [
    164721, 70435, 163995, 164525, 6305, 164506,
    66831, 93275, 127854, 104939, 130159, 75907,
    65654, 83383, 9441, 40983, 139567, 41334,
    22679, 18739, 95712, 163854, 163645, 163638
]

NEGATIVE_CONTROL_PIDS = [163861, 163870, 163872, 985, 121216]
SPECIAL_CASE_PIDS = [165114, 78763]

def main():
    conn_crm = psycopg2.connect("dbname=crm user=postgres")
    
    # 1. Fetch active canonical categories
    with conn_crm.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT category_code, category_name, is_active FROM crm_product_categories WHERE is_active = TRUE ORDER BY id")
        canonical_cats = [r["category_code"] for r in cur.fetchall()]
        
    print(f"Canonical categories ({len(canonical_cats)}): {canonical_cats}\n")

    # 2. Fetch latest v2 assessments for target PIDs
    all_pids = list(set(REGRESSION_24_PIDS + NEGATIVE_CONTROL_PIDS + SPECIAL_CASE_PIDS))
    with conn_crm.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT DISTINCT ON (procurement_id)
                id, procurement_id, prompt_version, model_name,
                validated_model_result, created_at
            FROM crm_v3_model_inference_runs
            WHERE procurement_id = ANY(%s) AND prompt_version = 'v3_second_pass_evidence_7b_v2'
            ORDER BY procurement_id, id DESC
        """, (all_pids,))
        assessments = {r["procurement_id"]: r for r in cur.fetchall()}

    print(f"Loaded {len(assessments)} latest v2 assessments from DB.\n")

    # 3. Build Category Distribution Matrix for Regression 24
    cat_matrix = {cat: {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0, "TOTAL": 0} for cat in canonical_cats}
    cat_matrix["other_unmapped"] = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0, "TOTAL": 0}

    proc_diag_rows = []
    conflicts = []

    cat_gold_weak_ev = 0
    cat_pos_without_ev = 0
    cat_pos_without_trace = 0

    total_findings_v2 = 0
    supported_findings_v2 = 0
    unsupported_findings_v2 = 0

    print("=== PER-PROCUREMENT CATEGORY BREAKDOWN (N=24) ===")
    for pid in REGRESSION_24_PIDS:
        ass = assessments.get(pid)
        if not ass:
            print(f"PID={pid}: NOT FOUND IN V2 ASSESSMENTS")
            continue
        p_json = ass["validated_model_result"] if isinstance(ass["validated_model_result"], dict) else json.loads(ass["validated_model_result"] or "{}")
        
        overall_medal = p_json.get("model_medal", "WOOD")
        overall_score = p_json.get("model_score", 0)
        cat_evals = p_json.get("category_evaluations", [])
        found_facts = p_json.get("found_facts", [])
        
        # Determine strongest category medal
        medal_rank = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, "NONE": 0}
        strongest_cat = None
        strongest_medal = "WOOD"
        strongest_rank = 0

        print(f"\n[PID {pid}] Overall: Medal={overall_medal} Score={overall_score} | Categories: {len(cat_evals)} | Facts: {len(found_facts)}")
        print(f"  Reason: {p_json.get('model_reason')}")
        
        for f in found_facts:
            total_findings_v2 += 1
            supported_findings_v2 += 1
            print(f"  * Fact: '{f.get('product_name_normalized')}' (Cat: {f.get('category_code')}) | Quote: '{f.get('source_quote')}' | Supp: {f.get('support_type')}")

        for c_eval in cat_evals:
            c_code = str(c_eval.get("category_code") or "")
            c_medal = str(c_eval.get("category_model_medal") or "WOOD").upper()
            c_score = c_eval.get("category_model_score", 0)
            ev_refs = c_eval.get("category_evidence_refs") or c_eval.get("evidence_refs") or []
            f_cnt = c_eval.get("findings_count", 0)
            
            print(f"  -> Cat: '{c_code}' | Medal: {c_medal} (Score={c_score}) | Findings: {f_cnt} | EvRefs: {len(ev_refs)}")
            print(f"     Reason: {c_eval.get('category_reason')}")
            for ref in ev_refs:
                print(f"       - Ref: {ref.get('document_name')} | Term: {ref.get('matched_term')} | Loc: {ref.get('location')}")

            target_cat = c_code if c_code in cat_matrix else "other_unmapped"
            if c_medal in cat_matrix[target_cat]:
                cat_matrix[target_cat][c_medal] += 1
                cat_matrix[target_cat]["TOTAL"] += 1
                
            rank = medal_rank.get(c_medal, 0)
            if rank > strongest_rank:
                strongest_rank = rank
                strongest_medal = c_medal
                strongest_cat = c_code

            if c_medal in ("GOLD", "SILVER", "BRONZE") and len(ev_refs) == 0 and f_cnt == 0:
                cat_pos_without_ev += 1

            if c_medal == "GOLD" and len(ev_refs) < 2 and f_cnt == 0:
                cat_gold_weak_ev += 1

            if c_medal in ("GOLD", "SILVER", "BRONZE"):
                for ref in ev_refs:
                    if not ref.get("document_name"):
                        cat_pos_without_trace += 1

        is_match = (overall_medal == (strongest_medal if strongest_cat else "WOOD"))
        proc_diag_rows.append({
            "pid": pid,
            "overall_medal": overall_medal,
            "overall_score": overall_score,
            "strongest_cat": strongest_cat or "NONE",
            "strongest_medal": strongest_medal if strongest_cat else "WOOD",
            "match": is_match,
            "cat_count": len(cat_evals)
        })
        if not is_match:
            conflicts.append({
                "pid": pid,
                "overall_medal": overall_medal,
                "strongest_cat": strongest_cat or "NONE",
                "strongest_medal": strongest_medal if strongest_cat else "WOOD",
                "reason": p_json.get("model_reason", "")
            })

    print("\n" + "=" * 75)
    print("=== PROOF METRICS ===")
    print("=" * 75)
    print(f"UNSUPPORTED_FINDINGS={unsupported_findings_v2}")
    print(f"SUPPORTED_FINDINGS={supported_findings_v2}")
    print(f"CATEGORY_GOLD_WEAK_EVIDENCE={cat_gold_weak_ev}")
    print(f"CATEGORY_POSITIVE_MEDAL_WITHOUT_EVIDENCE={cat_pos_without_ev}")
    print(f"POSITIVE_CATEGORY_RESULTS_WITHOUT_TRACE={cat_pos_without_trace}")

    print("\n" + "=" * 75)
    print("=== CATEGORY DISTRIBUTION MATRIX (REGRESSION N=24) ===")
    print("=" * 75)
    print(f"{'CATEGORY':<32} | {'GOLD':<5} | {'SILVER':<7} | {'BRONZE':<7} | {'WOOD':<5} | {'TOTAL':<5}")
    print("-" * 75)
    for cat, counts in cat_matrix.items():
        if counts["TOTAL"] > 0 or cat in canonical_cats:
            print(f"{cat:<32} | {counts['GOLD']:<5} | {counts['SILVER']:<7} | {counts['BRONZE']:<7} | {counts['WOOD']:<5} | {counts['TOTAL']:<5}")

    print("\n" + "=" * 75)
    print("=== PROCUREMENT CATEGORY ALIGNMENT (N=24) ===")
    print("=" * 75)
    print(f"{'PID':<8} | {'OVERALL':<8} | {'STRONGEST_CAT':<28} | {'STRONGEST_MEDAL':<15} | {'MATCH':<6}")
    print("-" * 75)
    matches_cnt = 0
    for r in proc_diag_rows:
        if r["match"]:
            matches_cnt += 1
        print(f"{r['pid']:<8} | {r['overall_medal']:<8} | {r['strongest_cat']:<28} | {r['strongest_medal']:<15} | {str(r['match']):<6}")
    print(f"\nExact Overall == Strongest Category Alignment: {matches_cnt}/{len(proc_diag_rows)} ({matches_cnt/len(proc_diag_rows)*100:.1f}%)")

    print("\n" + "=" * 75)
    print("=== OVERALL CATEGORY CONFLICTS ===")
    print("=" * 75)
    print(f"Total Conflicts: {len(conflicts)}")
    for c in conflicts:
        print(f"PID={c['pid']:<7} | Overall={c['overall_medal']:<6} vs StrongestCat={c['strongest_medal']:<6} ({c['strongest_cat']}) | Reason: {c['reason']}")

    print("\n" + "=" * 75)
    print("=== NEGATIVE CONTROLS (N=5) ===")
    print("=" * 75)
    for pid in NEGATIVE_CONTROL_PIDS:
        ass = assessments.get(pid)
        if ass:
            p_json = ass["validated_model_result"] if isinstance(ass["validated_model_result"], dict) else json.loads(ass["validated_model_result"] or "{}")
            print(f"PID={pid:<7} | Medal={p_json.get('model_medal'):<6} | Score={p_json.get('model_score'):<3} | Facts={len(p_json.get('found_facts', []))} | Reason={p_json.get('model_reason')}")

    print("\n" + "=" * 75)
    print("=== SPECIAL AUDIT CASES (165114 & 78763) ===")
    print("=" * 75)
    for pid in SPECIAL_CASE_PIDS:
        ass = assessments.get(pid)
        if ass:
            p_json = ass["validated_model_result"] if isinstance(ass["validated_model_result"], dict) else json.loads(ass["validated_model_result"] or "{}")
            print(f"\nPID={pid:<7} | Medal={p_json.get('model_medal'):<6} | Score={p_json.get('model_score'):<3} | Facts={len(p_json.get('found_facts', []))}")
            print(f"Reason: {p_json.get('model_reason')}")
            print("Categories:")
            for ce in p_json.get("category_evaluations", []):
                ev_refs = ce.get("category_evidence_refs") or ce.get("evidence_refs") or []
                print(f"  * {ce.get('category_code')}: Medal={ce.get('category_model_medal')} Score={ce.get('category_model_score')} EvRefs={len(ev_refs)}")
                for ref in ev_refs:
                    print(f"      - Ref: {ref.get('document_name')} | Term: {ref.get('matched_term')} | Loc: {ref.get('location')}")
            print("Facts:")
            for f in p_json.get("found_facts", []):
                print(f"  * {f.get('product_name_normalized')} (Cat: {f.get('category_code')}) | Quote: '{f.get('source_quote')}' | Supp: {f.get('support_type')}")
        else:
            print(f"PID={pid}: Not found in DB")

if __name__ == "__main__":
    main()
