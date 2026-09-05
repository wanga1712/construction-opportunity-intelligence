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
    crm_cur.execute('SELECT id, okpd_code, auction_name FROM crm_procurements WHERE id = ANY(%s)', (pids,))
    for r in crm_cur.fetchall():
        crm_map[r['id']] = r

unresolved = []
for r in qrows:
    if r['v4_confirmed'] == 0 and (r['v4_unknown'] > 0 or r['pending_val'] > 0):
        c = crm_map.get(r['procurement_id'], {})
        r['okpd_code'] = c.get('okpd_code')
        r['title'] = (c.get('auction_name') or '')[:70]
        unresolved.append(r)

print("Total unresolved completed procurements:", len(unresolved))
for u in unresolved:
    print(f"PID {u['procurement_id']}: OKPD={u['okpd_code']} | unknown={u['v4_unknown']} | pending={u['pending_val']} | rej={u['v4_rejected']} | {u['title']}")
