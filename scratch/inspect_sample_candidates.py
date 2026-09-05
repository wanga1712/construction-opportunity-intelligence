import sys, json, psycopg2, psycopg2.extras
sys.path.insert(0, '/opt/CRM_Streamlit')
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
)
doc_conn = get_doc_db_connection()

sample_pids = [
    163865, # 42.11 Ремонт моста
    163869, # 26.3 Коммутатор
    163931, # 43.29 Монтаж СКУД
    163932, # 43.39 Ремонт электропроводки
    163935, # 27.12 Вакуумные выключатели
    163936, # 26.20 МФУ, системные блоки
    163941, # 43.21 Монтаж охранной сигнализации
    164477, # 26.20 Поставка сервера
    164506, # 26.20 Поставка серверного оборудования
    164509, # 27.40 Поставка светильников и кабеля
    164699, # 27.32 Поставка электроматериалов
    165148, # 42.11 Ремонт автодорог
]

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute('''
        SELECT id, procurement_id, matched_term, category_code, validation_status, validation_reason, row_data
        FROM document_match_details
        WHERE procurement_id = ANY(%s)
        ORDER BY procurement_id, id
    ''', (sample_pids,))
    details = cur.fetchall()

print(f"Fetched {len(details)} details for {len(sample_pids)} sample procurements")
by_pid = {}
for d in details:
    by_pid.setdefault(d['procurement_id'], []).append(d)

for pid in sample_pids:
    dt_list = by_pid.get(pid, [])
    print(f"\n================ PID {pid} ({len(dt_list)} candidates) ================")
    for dt in dt_list[:5]:
        print(f"  [{dt['category_code']}] '{dt['matched_term']}' -> Status: {dt['validation_status']}")
        print(f"    Reason: {dt['validation_reason']}")
        print(f"    RowData: {str(dt['row_data'])[:140]}")
