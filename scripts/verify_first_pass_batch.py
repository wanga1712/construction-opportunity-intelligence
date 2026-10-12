"""Control Batch Verification Script: First Pass & Queue Claim Simulation on 50 Representative Active Procurements."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

import psycopg2
from psycopg2.extras import RealDictCursor

from src.services.first_pass.service import FirstPassService

LANE_RANKS = {
    "crm_active_hot": 1,
    "open_active": 2,
    "awarded_recent": 3,
    "retry": 4,
    "historical_awarded": 5,
}


def get_lane_rank(lane: str) -> int:
    return LANE_RANKS.get(lane, 6)


class S13CrmDb:
    def execute_query(self, sql, params=None):
        try:
            conn = psycopg2.connect(dbname="crm", host="/var/run/postgresql", user="postgres")
        except Exception:
            conn = psycopg2.connect(
                host=os.getenv("CRM_DB_HOST", "127.0.0.1"),
                port=int(os.getenv("CRM_DB_PORT", "5432")),
                dbname=os.getenv("CRM_DB_NAME", "crm"),
                user=os.getenv("CRM_DB_USER", "crm_app"),
                password=os.getenv("CRM_DB_PASSWORD", ""),
            )
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_doc_db_conn():
    from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn
    return _get_doc_db_conn()


def run_batch_verification(sample_size: int = 100) -> None:
    print(f"[{datetime.now().isoformat()}] Starting First Pass Control Batch Verification (N={sample_size})...\n")

    crm_db = S13CrmDb()
    service = FirstPassService(crm_db)

    # 1. Fetch 100 representative active procurements covering diverse types:
    # - 40 with Category Opportunities
    # - 30 with AI assessments
    # - 30 fresh / OKPD prior rows
    sql_opps = """
        SELECT DISTINCT ON (p.id) p.id, p.source_table, p.source_id, p.contract_number, p.okpd_code,
               p.auction_name, p.end_date, p.crm_stage, p.initial_price, p.object_type
        FROM crm_procurements p
        JOIN crm_procurement_category_opportunities o ON p.id = o.procurement_id
        WHERE p.crm_stage IN ('torgi', 'submission_open')
        ORDER BY p.id DESC
        LIMIT 50
    """
    sql_ai = """
        SELECT DISTINCT ON (p.id) p.id, p.source_table, p.source_id, p.contract_number, p.okpd_code,
               p.auction_name, p.end_date, p.crm_stage, p.initial_price, p.object_type
        FROM crm_procurements p
        JOIN procurement_ai_assessments a ON p.id = a.procurement_id
        WHERE p.crm_stage IN ('torgi', 'submission_open')
        AND a.is_current = TRUE
        ORDER BY p.id DESC
        LIMIT 50
    """
    sql_fresh = """
        SELECT p.id, p.source_table, p.source_id, p.contract_number, p.okpd_code,
               p.auction_name, p.end_date, p.crm_stage, p.initial_price, p.object_type
        FROM crm_procurements p
        WHERE p.crm_stage IN ('torgi', 'submission_open')
        ORDER BY p.id DESC
        LIMIT 80
    """

    procs_opps = crm_db.execute_query(sql_opps) or []
    procs_ai = crm_db.execute_query(sql_ai) or []
    procs_fresh = crm_db.execute_query(sql_fresh) or []

    combined_dict = {}
    for p in procs_opps + procs_ai + procs_fresh:
        if len(combined_dict) >= sample_size:
            break
        combined_dict[p["id"]] = p

    procs = list(combined_dict.values())[:sample_size]
    pids = [p["id"] for p in procs]
    print(f"Loaded {len(procs)} representative active procurements (crm_stage in ('torgi', 'submission_open')).")

    # 2. Query existing document_processing_queue tasks (read-only diagnostic)
    queue_map = {}
    try:
        doc_conn = get_doc_db_conn()
        with doc_conn.cursor() as cur:
            cur.execute(
                """
                SELECT procurement_id, queue_lane, status, priority_score, candidate_level, procurement_scope_type
                FROM document_processing_queue
                WHERE procurement_id = ANY(%s)
                ORDER BY id DESC
                """,
                (pids,),
            )
            for r in cur.fetchall() or []:
                pid = r[0]
                if pid not in queue_map:
                    queue_map[pid] = {
                        "queue_lane": r[1] or "open_active",
                        "queue_status": r[2] or "pending",
                    }
        doc_conn.close()
    except Exception as e:
        print(f"Notice: Could not read document_processing_queue directly ({e}); using defaults.")

    for p in procs:
        q_info = queue_map.get(p["id"], {})
        p["queue_lane"] = q_info.get("queue_lane", "open_active")
        p["queue_status"] = q_info.get("queue_status", "pending")

    # 3. Batch Evaluate First Pass
    now = datetime.now(timezone.utc)
    results = service.evaluate_batch(procs, now=now)

    # 4. Multiplicity Proof on the sample
    multiplicity_counts = {}
    for pid, res in results.items():
        cnt = res.category_opportunity_count
        multiplicity_counts[cnt] = multiplicity_counts.get(cnt, 0) + 1

    print("\n--- MULTIPLICITY PROOF ON SAMPLE ---")
    for opp_count, num_procs in sorted(multiplicity_counts.items()):
        print(f"  Procurements with {opp_count} Category Opportunity records: {num_procs} ({(num_procs/len(procs))*100:.1f}%)")

    # 5. Production ORDER BY Simulation (READ-ONLY)
    simulated_items = []
    for p in procs:
        pid = p["id"]
        res = results.get(pid)
        if not res:
            continue
        lane = p.get("queue_lane", "open_active")
        lane_rank = get_lane_rank(lane)
        simulated_items.append((lane_rank, res, p))

    simulated_items.sort(
        key=lambda x: (
            x[0],
            -x[1].priority_score,
            (x[1].submission_end_at is None, x[1].submission_end_at or datetime.max.replace(tzinfo=timezone.utc)),
            x[1].procurement_id,
        )
    )

    print("\n" + "=" * 185)
    print(f"SIMULATED PRODUCTION CLAIM ORDER (TOP {min(len(simulated_items), 100)} ITEMS)")
    print("=" * 185)
    print(
        f"{'Rank':<5} | {'CRM ID':<8} | {'Contract Number':<19} | {'OKPD':<10} | {'Family':<13} | {'Obj Type':<12} | "
        f"{'Source':<19} | {'Medal':<8} | {'Score':<5} | {'Base':<4} | {'Urg':<3} | {'Rel':<3} | {'Final':<6} | {'Days':<7} | {'Lane':<11} | {'Status':<9}"
    )
    print("-" * 185)

    top_100_direct_supply_count = 0
    for rank, (lane_rank, res, p) in enumerate(simulated_items[:100], 1):
        contract_num = (res.contract_number or "")[:19]
        days_str = f"{res.days_to_deadline:.1f}d" if res.days_to_deadline is not None else "—"
        okpd_s = str(p.get("okpd_code") or "—")[:10]
        obj_t = str(res.object_type or "—")[:12]

        if res.object_family == "DIRECT_SUPPLY":
            top_100_direct_supply_count += 1

        print(
            f"#{rank:<4} | {res.procurement_id:<8} | {contract_num:<19} | {okpd_s:<10} | {res.object_family:<13} | {obj_t:<12} | "
            f"{res.canonical_preliminary_source:<19} | {res.canonical_preliminary_medal:<8} | {res.canonical_preliminary_score:<5.0f} | "
            f"{res.medal_base:<4} | {res.urgency_bonus:<3} | {res.relevance_bonus:<3} | {res.priority_score:<6} | {days_str:<7} | "
            f"{res.queue_lane:<11} | {res.queue_status:<9}"
        )

    print("=" * 185)

    # 6. Distribution Summary & Invariants Check
    medals = {}
    sources = {}
    families = {}
    double_counting_violations = []

    for _, res, _ in simulated_items:
        medals[res.canonical_preliminary_medal] = medals.get(res.canonical_preliminary_medal, 0) + 1
        sources[res.canonical_preliminary_source] = sources.get(res.canonical_preliminary_source, 0) + 1
        families[res.object_family] = families.get(res.object_family, 0) + 1

        # Double counting check
        if res.canonical_preliminary_source == "CATEGORY_OKPD_PRIOR" and res.relevance_bonus > 0:
            double_counting_violations.append(res.procurement_id)

    total_eval = len(simulated_items)
    gold_pct = (medals.get("GOLD", 0) / total_eval * 100) if total_eval else 0
    silver_pct = (medals.get("SILVER", 0) / total_eval * 100) if total_eval else 0
    bronze_pct = (medals.get("BRONZE", 0) / total_eval * 100) if total_eval else 0
    wood_pct = (medals.get("WOOD", 0) / total_eval * 100) if total_eval else 0
    unassessed_pct = (medals.get("UNASSESSED", 0) / total_eval * 100) if total_eval else 0

    top_100_direct_pct = (top_100_direct_supply_count / min(len(simulated_items), 100) * 100) if simulated_items else 0
    double_counting_check = "PASS" if len(double_counting_violations) == 0 else f"FAIL ({len(double_counting_violations)} violations)"

    print("\n--- BEFORE MUTATION REPORT METRICS ---")
    print(f"OKPD_PRIOR_V1_SOURCE=src/learning/okpd_prior/model.py (OKPDResearchHitModelV1 CatBoost shadow model)")
    print(f"CATEGORY_PRIOR_SOURCE=crm_category_okpd_priors (curated discrete weights 80/70/50/35)")
    print(f"CANONICAL_GOLD_PERCENT={gold_pct:.2f}%")
    print(f"CANONICAL_SILVER_PERCENT={silver_pct:.2f}%")
    print(f"CANONICAL_BRONZE_PERCENT={bronze_pct:.2f}%")
    print(f"CANONICAL_WOOD_PERCENT={wood_pct:.2f}%")
    print(f"UNASSESSED_PERCENT={unassessed_pct:.2f}%")
    import json
    print(f"MEDAL_SOURCE_DISTRIBUTION={json.dumps(sources, ensure_ascii=False)}")
    print(f"SOCIAL_COUNT={families.get('SOCIAL', 0)}")
    print(f"COMMERCIAL_COUNT={families.get('COMMERCIAL', 0)}")
    print(f"DIRECT_SUPPLY_COUNT={families.get('DIRECT_SUPPLY', 0)}")
    print(f"OTHER_COUNT={families.get('OTHER', 0)}")
    print(f"TOP100_DIRECT_SUPPLY_PERCENT={top_100_direct_pct:.2f}%")
    print(f"DOUBLE_COUNTING_CHECK={double_counting_check}")

    print("\n--- INVARIANT & SAFETY GATE VERIFICATIONS ---")
    print(f"  1. Gold Gate (Constraint: <= 60%): {gold_pct:.2f}% -> {'PASS' if gold_pct <= 60.0 else 'FAIL (BLOCK)'}")
    print(f"  2. Double Counting Check: -> {double_counting_check}")

    wood_scores = [res.priority_score for _, res, _ in simulated_items if res.canonical_preliminary_medal == "WOOD"]
    gold_scores = [res.priority_score for _, res, _ in simulated_items if res.canonical_preliminary_medal == "GOLD"]

    if wood_scores:
        max_wood = max(wood_scores)
        print(f"  3. Max Wood Score: {max_wood} (Constraint: <= 40) -> {'PASS' if max_wood <= 40 else 'FAIL'}")
    if gold_scores:
        min_gold = min(gold_scores)
        print(f"  4. Min Gold Score: {min_gold} (Constraint: >= 70 or 0 if expired) -> {'PASS' if all(s >= 70 or s == 0 for s in gold_scores) else 'FAIL'}")

    print("\n[OK] First Pass Control Batch & Live Queue Verification Complete.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=2000)
    args = parser.parse_args()
    run_batch_verification(args.sample)
