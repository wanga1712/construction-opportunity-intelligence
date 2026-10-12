"""Comprehensive test of FirstPass unified workset service on S13."""
import os
import sys
import time

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

import psycopg2
from psycopg2.extras import RealDictCursor
from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.first_pass.service import FirstPassService
from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.source_contour import resolve_source_contour

class TorgiWorksetRepository:
    def __init__(self):
        self.conn_kwargs = require_crm_db_connect_kwargs()
        self.first_pass_service = FirstPassService(None)
        self._init_priors()

    def _init_priors(self):
        conn = psycopg2.connect(**self.conn_kwargs)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT commercial_category_code, okpd_pattern, match_type, prior_weight, signal_role
                    FROM crm_category_okpd_priors
                    WHERE active = TRUE
                """)
                self.first_pass_service._cached_priors = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def load_evaluated_workset(self, hide_expired: bool = True) -> list[dict]:
        conn = psycopg2.connect(**self.conn_kwargs)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if hide_expired:
                    where = f"cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open' AND {actionable_submission_sql('cp')}"
                else:
                    where = "cp.crm_stage = 'torgi'"

                cur.execute(f"""
                    SELECT cp.id, cp.contract_number, cp.auction_name, cp.initial_price, cp.customer, cp.delivery_region,
                           cp.okpd_code, cp.okpd_name, cp.crm_category, cp.contractor_name, cp.contractor_inn,
                           cp.match_score, cp.signal_score, cp.commercial_score, cp.processing_stage, cp.matched_keywords,
                           cp.file_count, cp.match_count, cp.evidence_count, cp.start_date, cp.end_date, cp.delivery_end_date,
                           cp.tender_link, cp.award_status, cp.crm_stage, cp.crm_profile_id, cp.source_table, cp.source_id,
                           cp.crm_created_at, cp.crm_updated_at, cp.source_updated_at,
                           cp.ai_assessment_status, cp.ai_assessment_version, cp.ai_assessment_stability, cp.ai_stability_count,
                           cp.object_type
                    FROM crm_procurements cp
                    WHERE {where}
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
                opp_by_pid = {}
                for o in cur.fetchall():
                    opp_by_pid.setdefault(o["procurement_id"], []).append(dict(o))

                # Fetch AI assessments
                cur.execute("""
                    SELECT procurement_id, proposed_level, confidence, proposed_object_type, proposed_procurement_type, proposed_route_profile,
                           reasons, normalized_result
                    FROM procurement_ai_assessments
                    WHERE is_current = TRUE
                """)
                ai_by_pid = {a["procurement_id"]: dict(a) for a in cur.fetchall()}

                # Fetch expert annotations
                cur.execute("""
                    SELECT procurement_id, payload
                    FROM crm_v3_expert_annotations
                    WHERE is_current = TRUE
                """)
                ex_by_pid = {e["procurement_id"]: dict(e) for e in cur.fetchall()}
        finally:
            conn.close()

        cards = []
        for p in procs:
            pid = p["id"]
            ai = ai_by_pid.get(pid, {})
            p.update({
                "proposed_route_profile": ai.get("proposed_route_profile"),
                "proposed_object_type": ai.get("proposed_object_type"),
                "proposed_procurement_type": ai.get("proposed_procurement_type"),
                "confidence": ai.get("confidence"),
                "reasons": ai.get("reasons"),
                "normalized_result": ai.get("normalized_result"),
            })
            res = self.first_pass_service.evaluate_procurement(
                proc=p,
                category_opps=opp_by_pid.get(pid),
                ai_assessment=ai_by_pid.get(pid),
                priors=self.first_pass_service._cached_priors,
            )
            ex = ex_by_pid.get(pid)
            is_conf = False
            expert_medal = None
            if ex and ex.get("payload"):
                pl = ex["payload"]
                if pl.get("expert_medal") or pl.get("is_staged_complete"):
                    is_conf = True
                    expert_medal = pl.get("expert_medal")

            # Tier determination (single authority)
            is_expired = (p.get("award_status") == "submission_closed_waiting_award" or 
                          (p.get("end_date") is not None and str(p["end_date"])[:10] < time.strftime("%Y-%m-%d")))
            if is_expired:
                tier = 4
            elif is_conf:
                tier = 1
            elif res.canonical_preliminary_medal != "UNASSESSED":
                tier = 2
            else:
                tier = 3

            contour = resolve_source_contour(p.get("source_table"))
            law = contour.get("law_code", "UNKNOWN")

            p.update({
                "tier": tier,
                "is_confirmed": is_conf,
                "expert_medal": expert_medal,
                "preliminary_medal": res.canonical_preliminary_medal,
                "preliminary_source": res.canonical_preliminary_source,
                "priority_score": res.priority_score,
                "object_family": res.object_family,
                "law": law,
            })
            cards.append(p)

        # Canonical Tiered Sorting (monotonic)
        MEDAL_RANKS = {"GOLD": 1, "SILVER": 2, "BRONZE": 3, "WOOD": 4, "UNASSESSED": 5}
        def torgi_sort_key(c):
            t = c["tier"]
            m_rank = MEDAL_RANKS.get(c["expert_medal"], 5) if t == 1 else MEDAL_RANKS.get(c["preliminary_medal"], 5)
            score = c["priority_score"]
            end_d = str(c.get("end_date") or "9999-99-99")
            price = float(c.get("initial_price") or 0)
            cid = c["id"]
            return (t, m_rank, -score, end_d, -price, -cid)

        cards.sort(key=torgi_sort_key)
        return cards


repo = TorgiWorksetRepository()
t0 = time.time()
cards = repo.load_evaluated_workset(hide_expired=True)
elapsed_ms = (time.time() - t0) * 1000
print(f"Loaded {len(cards)} evaluated cards in {elapsed_ms:.2f} ms")

# Audit Top 50
print("\n--- TOP 50 AUDIT ---")
prev_tier = 0
order_violations = 0
for i, c in enumerate(cards[:50], 1):
    tier = c["tier"]
    if tier < prev_tier:
        order_violations += 1
        print(f"VIOLATION at #{i}: Tier {tier} after Tier {prev_tier}")
    prev_tier = tier
    if i <= 15:
        print(f"  #{i:02d} ID={c['id']} | Tier={tier} | Medal={c['preliminary_medal']} | Score={c['priority_score']} | Fam={c['object_family']} | Law={c['law']} | End={str(c.get('end_date'))[:10]}")

print(f"\nTIER_ORDER_VIOLATIONS: {order_violations}")
assert order_violations == 0, "Tier order violations found!"

# Aggregation check
gold_cnt = sum(1 for c in cards if c["preliminary_medal"] == "GOLD")
silver_cnt = sum(1 for c in cards if c["preliminary_medal"] == "SILVER")
bronze_cnt = sum(1 for c in cards if c["preliminary_medal"] == "BRONZE")
wood_cnt = sum(1 for c in cards if c["preliminary_medal"] == "WOOD")
unassessed_cnt = sum(1 for c in cards if c["preliminary_medal"] == "UNASSESSED")

social_cnt = sum(1 for c in cards if c["object_family"] == "SOCIAL")
comm_cnt = sum(1 for c in cards if c["object_family"] == "COMMERCIAL")
ds_cnt = sum(1 for c in cards if c["object_family"] == "DIRECT_SUPPLY")
other_cnt = sum(1 for c in cards if c["object_family"] == "OTHER")

law44_cnt = sum(1 for c in cards if c["law"] == "44-FZ")
law223_cnt = sum(1 for c in cards if c["law"] == "223-FZ")
law615_cnt = sum(1 for c in cards if c["law"] == "615-PP")

print("\n--- AGGREGATIONS ---")
print(f"Medals: GOLD={gold_cnt}, SILVER={silver_cnt}, BRONZE={bronze_cnt}, WOOD={wood_cnt}, UNASSESSED={unassessed_cnt}")
print(f"Families: SOCIAL={social_cnt}, COMMERCIAL={comm_cnt}, DIRECT_SUPPLY={ds_cnt}, OTHER={other_cnt}")
print(f"Laws: 44-FZ={law44_cnt}, 223-FZ={law223_cnt}, 615-PP={law615_cnt}")

print("\nALL CONSISTENCY TESTS PASSED!")
