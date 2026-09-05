import psycopg2, psycopg2.extras, json
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection

class DummyDB:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, query, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return [dict(r) for r in cur.fetchall()]

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
crm_db = DummyDB(crm_conn)

ev_pids = [76286, 76859, 80973, 84475, 105689, 106637, 116375, 116536, 129606, 136065, 139805, 142394, 142413, 150194, 152543, 152548, 152550, 152663, 160573, 160640, 160641, 160642, 160643, 160644, 160645, 160646, 160648, 160650, 160658, 160660, 160661, 160666, 160667, 160668, 160669]

projs = load_research_ui_projection(ev_pids, crm_db)

counts = {}
for p in projs.values():
    counts[p.research_state] = counts.get(p.research_state, 0) + 1

print("EVIDENCE PIDS PROJECTION COUNTS:")
print(json.dumps(counts, indent=2))

positive_sample = [p for p in projs.values() if p.research_state == 'EVIDENCE_FOUND']
print(f"FOUND {len(positive_sample)} EVIDENCE_FOUND PIDS:")
for p in positive_sample[:5]:
    print(f"  PID={p.procurement_id}, state={p.research_state}, gen_hash={p.research_generation_hash}, evidence={p.evidence_count}, categories={p.category_names}")
