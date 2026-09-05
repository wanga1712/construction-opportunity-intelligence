import sys, json, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit')
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
)
doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

PIPELINE_GENERATION = 'S13_V4_EXHAUSTIVE_CONTEXT'
VALIDATOR_NAME = 'context_validator'
VALIDATOR_VERSION = 'v4'
VALIDATION_METHOD = 'QWEN_CONTEXT_V4'

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as doc_cur:
    doc_cur.execute('''
        WITH detail_counts AS (
            SELECT 
                procurement_id,
                count(*) as total_details,
                count(*) FILTER (
                    WHERE validation_status = 'CONFIRMED' 
                      AND validator_name = %s 
                      AND lower(validator_version) = %s 
                      AND upper(validation_method) = %s
                ) as v4_confirmed,
                count(*) FILTER (
                    WHERE validation_status = 'REJECTED' 
                      AND validator_name = %s 
                      AND lower(validator_version) = %s 
                      AND upper(validation_method) = %s
                ) as v4_rejected,
                count(*) FILTER (
                    WHERE validation_status = 'UNKNOWN' 
                      AND validator_name = %s 
                      AND lower(validator_version) = %s 
                      AND upper(validation_method) = %s
                ) as v4_unknown,
                count(*) FILTER (WHERE validated_at IS NULL) as pending_val
            FROM document_match_details
            WHERE pipeline_generation = %s
            GROUP BY procurement_id
        )
        SELECT 
            q.procurement_id,
            q.completed_at,
            COALESCE(dc.total_details, 0) as total_details,
            COALESCE(dc.v4_confirmed, 0) as v4_confirmed,
            COALESCE(dc.v4_rejected, 0) as v4_rejected,
            COALESCE(dc.v4_unknown, 0) as v4_unknown,
            COALESCE(dc.pending_val, 0) as pending_val
        FROM document_processing_queue q
        LEFT JOIN detail_counts dc ON dc.procurement_id = q.procurement_id
        WHERE q.status = 'COMPLETED'
          AND q.pipeline_generation = %s
        ORDER BY q.procurement_id ASC
    ''', (
        VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper(),
        VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper(),
        VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper(),
        PIPELINE_GENERATION, PIPELINE_GENERATION
    ))
    qrows = doc_cur.fetchall()

pids = [r['procurement_id'] for r in qrows]
crm_map = {}
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as crm_cur:
    crm_cur.execute('SELECT id, okpd_code, auction_name, initial_price FROM crm_procurements WHERE id = ANY(%s)', (pids,))
    for r in crm_cur.fetchall():
        crm_map[r['id']] = r

unresolved = []
for r in qrows:
    if r['v4_confirmed'] == 0 and (r['v4_unknown'] > 0 or r['pending_val'] > 0):
        c = crm_map.get(r['procurement_id'], {})
        r['okpd_code'] = c.get('okpd_code')
        r['auction_name'] = c.get('auction_name')
        r['initial_price'] = c.get('initial_price')
        unresolved.append(r)

# Stratify by OKPD root
by_root = {}
for u in unresolved:
    root = (u['okpd_code'] or 'UNKNOWN').split('.')[0]
    by_root.setdefault(root, []).append(u)

print(f"Total unresolved: {len(unresolved)} across {len(by_root)} OKPD roots:")
for root, items in sorted(by_root.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"  Root {root}: {len(items)} procurements")

# Select a balanced deterministic cohort across all available roots
# For example, select up to 3-5 procurements per root deterministically sorted by procurement_id
selected_cohort = []
for root in sorted(by_root.keys()):
    root_items = sorted(by_root[root], key=lambda x: x['procurement_id'])
    # Take first 3-5 items from each root
    selected_cohort.extend(root_items[:4])

print(f"\nConstructed FRESH_RECHECK cohort of {len(selected_cohort)} items (score-blind stratified selection):")
for s in selected_cohort:
    print(f"  PID {s['procurement_id']}: OKPD={s['okpd_code']} | unknown={s['v4_unknown']} | pending={s['pending_val']} | {s['auction_name'][:65]}")
