"""Evaluate all 982 active actionable torgi with FirstPassService on S13."""
import os
import sys
sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

import psycopg2
from psycopg2.extras import RealDictCursor
from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.first_pass.service import FirstPassService
from src.services.commercial_routing_v3.submission_window import actionable_submission_sql

conn = psycopg2.connect(**require_crm_db_connect_kwargs())
with conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute(f"""
        SELECT cp.id, cp.contract_number, cp.okpd_code, cp.auction_name, cp.initial_price, cp.end_date,
               cp.object_type, cp.source_table, cp.source_id, cp.award_status, cp.crm_stage
        FROM crm_procurements cp
        WHERE cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open' AND {actionable_submission_sql('cp')}
        ORDER BY cp.id
    """)
    procs = [dict(r) for r in cur.fetchall()]

    # Fetch category opps
    cur.execute("""
        SELECT id, procurement_id, candidate_medal, commercial_priority_score, commercial_category_code,
               commercial_subcategory_code, confirmed_base_medal, status
        FROM crm_procurement_category_opportunities
        WHERE status = 'CURRENT'
    """)
    opp_rows = cur.fetchall()
    opp_by_pid = {}
    for o in opp_rows:
        opp_by_pid.setdefault(o["procurement_id"], []).append(dict(o))

    # Fetch AI assessments
    cur.execute("""
        SELECT procurement_id, proposed_level, confidence, proposed_object_type, proposed_procurement_type, proposed_route_profile
        FROM procurement_ai_assessments
        WHERE is_current = TRUE
    """)
    ai_rows = cur.fetchall()
    ai_by_pid = {a["procurement_id"]: dict(a) for a in ai_rows}

    # Fetch expert annotations
    cur.execute("""
        SELECT procurement_id, payload
        FROM crm_v3_expert_annotations
        WHERE is_current = TRUE
    """)
    ex_rows = cur.fetchall()
    ex_by_pid = {e["procurement_id"]: dict(e) for e in ex_rows}

service = FirstPassService(None)
cur = conn.cursor(cursor_factory=RealDictCursor)
cur.execute("SELECT commercial_category_code, okpd_pattern, match_type, prior_weight, signal_role FROM crm_category_okpd_priors WHERE active = TRUE")
service._cached_priors = [dict(r) for r in cur.fetchall()]

results = []
for p in procs:
    pid = p["id"]
    res = service.evaluate_procurement(
        proc=p,
        category_opps=opp_by_pid.get(pid),
        ai_assessment=ai_by_pid.get(pid),
        priors=service._cached_priors,
    )
    ex = ex_by_pid.get(pid)
    is_conf = False
    expert_medal = None
    if ex and ex.get("payload"):
        pl = ex["payload"]
        if pl.get("expert_medal") or pl.get("is_staged_complete"):
            is_conf = True
            expert_medal = pl.get("expert_medal")
    
    tier = 1 if is_conf else (2 if res.canonical_preliminary_medal != "UNASSESSED" else 3)
    results.append({
        "id": pid,
        "contract_number": p["contract_number"],
        "tier": tier,
        "is_confirmed": is_conf,
        "expert_medal": expert_medal,
        "preliminary_medal": res.canonical_preliminary_medal,
        "preliminary_source": res.canonical_preliminary_source,
        "priority_score": res.priority_score,
        "object_family": res.object_family,
        "end_date": str(p["end_date"]),
        "initial_price": float(p["initial_price"] or 0),
        "source_table": p["source_table"],
    })

print(f"Evaluated {len(results)} active actionable torgi:")
tier_counts = {}
medal_counts = {}
family_counts = {}
source_counts = {}
law_counts = {}

for r in results:
    tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
    medal_counts[r["preliminary_medal"]] = medal_counts.get(r["preliminary_medal"], 0) + 1
    family_counts[r["object_family"]] = family_counts.get(r["object_family"], 0) + 1
    source_counts[r["preliminary_source"]] = source_counts.get(r["preliminary_source"], 0) + 1
    
    st = r["source_table"] or ""
    law = "44-FZ" if "44" in st else ("223-FZ" if "223" in st else ("615-PP" if "615" in st else "OTHER"))
    law_counts[law] = law_counts.get(law, 0) + 1

print("Tier breakdown:", tier_counts)
print("Preliminary Medal breakdown:", medal_counts)
print("Preliminary Source breakdown:", source_counts)
print("Object Family breakdown:", family_counts)
print("Law breakdown:", law_counts)

# Top 10 sorted
MEDAL_RANKS = {"GOLD": 1, "SILVER": 2, "BRONZE": 3, "WOOD": 4, "UNASSESSED": 5}
def sort_key(r):
    return (
        r["tier"],
        MEDAL_RANKS.get(r["expert_medal"], 5) if r["tier"] == 1 else MEDAL_RANKS.get(r["preliminary_medal"], 5),
        -r["priority_score"],
        r["end_date"] or "9999-99-99",
        -r["initial_price"],
        -r["id"]
    )

sorted_results = sorted(results, key=sort_key)
print("\nTop 15 sorted:")
for i, r in enumerate(sorted_results[:15], 1):
    print(f"  #{i:02d} ID={r['id']} | Tier={r['tier']} | Medal={r['preliminary_medal']} | Score={r['priority_score']} | Fam={r['object_family']} | End={r['end_date']} | Law={r['source_table']}")

conn.close()
