import json
import os
import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import ContextValidator
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    enrich_candidates_with_crm_facts,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

taxonomy_snapshot = CrmTaxonomyLoader().load_snapshot()

# Query real rows from document_match_details
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    # 1. Obvious negatives (legal/admin text, fuzzy collisions, organization names)
    cur.execute("""
        SELECT d.id as detail_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.matched_term IN ('проспект', 'вектор', 'производствен', 'магистрал', 'административ')
        ORDER BY d.id ASC
        LIMIT 20
    """)
    raw_neg = cur.fetchall()

    # 2. Genuine ambiguous rows (short generic terms without brand context)
    cur.execute("""
        SELECT d.id as detail_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.matched_term IN ('покрытие', 'герметик', 'пропитка', 'состав', 'смесь', 'мембрана')
        ORDER BY d.id ASC
        LIMIT 20
    """)
    raw_amb = cur.fetchall()

    # 3. Real positive candidates (specific materials/terms)
    cur.execute("""
        SELECT d.id as detail_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.matched_term IN ('мастика', 'техноэласт', 'пенетрон', 'светильник', 'лоток', 'мембрана', 'эмако', 'топпинг', 'денстоп', 'манопур')
        ORDER BY d.id DESC
        LIMIT 30
    """)
    raw_pos = cur.fetchall()

enriched_neg = enrich_candidates_with_crm_facts(raw_neg, crm_conn, taxonomy_snapshot)
enriched_amb = enrich_candidates_with_crm_facts(raw_amb, crm_conn, taxonomy_snapshot)
enriched_pos = enrich_candidates_with_crm_facts(raw_pos, crm_conn, taxonomy_snapshot)

print(f"ENRICHED_NEG_COUNT={len(enriched_neg)}, ENRICHED_AMB_COUNT={len(enriched_amb)}, ENRICHED_POS_COUNT={len(enriched_pos)}")

# Save to json for inspection
with open("/opt/CRM_Streamlit/holdout_candidates.json", "w", encoding="utf-8") as f:
    json.dump({
        "neg": enriched_neg[:15],
        "amb": enriched_amb[:15],
        "pos": enriched_pos[:20]
    }, f, ensure_ascii=False, indent=2, default=str)

print("SAVED_HOLDOUT_CANDIDATES")
