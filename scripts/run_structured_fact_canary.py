import sys
import json
import uuid
import argparse
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/opt/CRM_Streamlit')

from src.services.category_opportunity_service import CategoryOpportunityService
from tender_documents_research.document_processor.r4_input_selector import build_r4_source_snapshot
from tender_documents_research.document_processor.structured_fact_extractor import (
    StructuredFactExtractor,
    default_ai_caller,
)
from tender_documents_research.document_processor.structured_fact_repository import save_extraction_run
from tender_documents_research.document_processor.structured_fact_adjudication import (
    adjudication_allows_trust,
    adjudication_metric_verdict,
)
from tender_documents_research.document_processor.structured_fact_contract import (
    STRUCTURED_EXTRACTOR_NAME,
    STRUCTURED_EXTRACTOR_VERSION,
    EXTRACTION_METHOD,
    PROMPT_VERSION,
    compute_sha256,
    verify_source_quote,
)

class S13DbManager:
    def execute_query(self, alias_or_sql, query_or_params, params_or_fetch=None, fetch=True):
        if alias_or_sql in ('document_intelligence', 'crm'):
            db_name = alias_or_sql
            sql = query_or_params
            params = params_or_fetch
        else:
            db_name = 'document_intelligence'
            sql = alias_or_sql
            params = query_or_params

        conn = psycopg2.connect(dbname=db_name, user="postgres", host="/var/run/postgresql")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            if fetch:
                return [dict(r) for r in cur.fetchall()]
            conn.commit()
            return []

COMMERCIAL_ENTITY_TYPES = {'PRODUCT', 'MATERIAL', 'EQUIPMENT'}

HARD_NEGATIVES = {
    'автомобильная дорога', 'капитальный ремонт', 'строительство', 
    'реконструкция', 'монтаж', 'устройство покрытия', 'проектирование'
}

MAX_CANARY_N = 150
INITIAL_CANARY_N = 60

def build_real_source_snapshot(row):
    return build_r4_source_snapshot(row)

def format_precision(claims_n, correct_n):
    if claims_n == 0:
        return "N/A"
    return f"{(correct_n / claims_n):.4f}"

def main(limit=INITIAL_CANARY_N):
    canary_batch_id = str(uuid.uuid4())
    print("=== CANONICAL REPRODUCIBLE STRUCTURED FACT REAL EXTRACTOR CANARY RUNNER ===")
    print(f"CANARY_BATCH_ID = {canary_batch_id}")

    conn_doc = psycopg2.connect("dbname=document_intelligence user=postgres host=/var/run/postgresql")
    cur_doc = conn_doc.cursor(cursor_factory=RealDictCursor)

    # 1. Fetch unexposed CONFIRMED details via NOT EXISTS selection (UNEXPOSED_BY_SELECTION = YES)
    cur_doc.execute("""
        WITH candidates AS (
            SELECT DISTINCT ON (d.id)
                d.id AS detail_id,
                d.match_id,
                d.procurement_id,
                d.category_code,
                d.subcategory_code,
                d.matched_term,
                d.row_data,
                d.context_before,
                d.context_after,
                d.page_or_sheet,
                d.row_number,
                d.validation_status,
                d.validator_name AS source_validator_name,
                d.validator_version AS source_validator_version,
                d.validation_method AS source_validation_method,
                m.document_name,
                m.archive_member_path,
                q.procurement_scope_type
            FROM document_match_details d
            JOIN document_processing_queue q ON d.procurement_id = q.procurement_id
            LEFT JOIN document_matches m ON m.id = d.match_id
            WHERE d.validation_status = 'CONFIRMED'
              AND NOT EXISTS (
                  SELECT 1
                  FROM structured_extraction_runs r
                  WHERE r.detail_id = d.id
                    AND r.extractor_version = %s
                    AND r.prompt_version = %s
              )
            ORDER BY d.id
        )
        SELECT *,
               CASE WHEN procurement_scope_type = 'DIRECT_GOODS'
                    THEN 'POSITIVE_LIKELY' ELSE 'NEGATIVE_LIKELY' END AS sampling_cohort
        FROM candidates
        ORDER BY sampling_cohort, category_code, detail_id
        LIMIT %s;
    """, (STRUCTURED_EXTRACTOR_VERSION, PROMPT_VERSION, min(limit, MAX_CANARY_N)))
    candidate_details = cur_doc.fetchall()
    print(f"Selected {len(candidate_details)} true unexposed details for real Qwen 7B canary.")

    model_call_attempted = 0
    model_response_received = 0
    model_failures = 0
    wrong_models = 0
    authority_rejects = 0

    def counted_ai_caller(prompt: str, model: str = "qwen2.5:7b", format_json: bool = True):
        nonlocal model_call_attempted, model_response_received
        model_call_attempted += 1
        raw_text, meta = default_ai_caller(prompt, model=model, format_json=format_json)
        model_response_received += 1
        return raw_text, meta

    extractor = StructuredFactExtractor(ai_caller=counted_ai_caller, model_name="qwen2.5:7b")

    canary_runs_created = 0
    model_successes = 0

    complete_runs = 0
    empty_runs = 0
    error_runs = 0

    promoted_entities = []
    
    # Adjudication and precision metrics
    prod_claims, prod_tp, prod_fp = 0, 0, 0
    disp_claims, disp_tp, disp_fp = 0, 0, 0
    qty_claims, qty_correct = 0, 0
    uprice_claims, uprice_correct = 0, 0
    tprice_claims, tprice_correct = 0, 0
    product_quote_claims, product_quote_valid = 0, 0
    quantity_quote_claims, quantity_quote_valid = 0, 0
    unit_price_quote_claims, unit_price_quote_valid = 0, 0
    total_price_quote_claims, total_price_quote_valid = 0, 0

    unit_price_no_evidence = 0
    total_price_no_evidence = 0

    scope_counts = {}

    for idx, d in enumerate(candidate_details, 1):
        detail_id = d['detail_id']
        proc_id = d['procurement_id']
        cat_code = d['category_code']
        subcat_code = d['subcategory_code']
        scope_type = d['procurement_scope_type'] or 'UNKNOWN'
        scope_counts[scope_type] = scope_counts.get(scope_type, 0) + 1
        
        snapshot_text = build_real_source_snapshot(d)
        snapshot_sha256 = compute_sha256(snapshot_text)

        candidate = {
            "detail_id": detail_id,
            "procurement_id": proc_id,
            "category_code": cat_code,
            "subcategory_code": subcat_code,
            "match_id": d['match_id'],
            "queue_id": None,
            "document_name": d.get('document_name'),
            "archive_member_path": d.get('archive_member_path'),
            "page_or_sheet": d['page_or_sheet'],
            "row_number": d['row_number'],
            "source_text_snapshot": snapshot_text,
            "source_text_sha256": snapshot_sha256,
            "validation_status": d['validation_status'],
            "source_validator_name": d.get('source_validator_name'),
            "source_validator_version": d.get('source_validator_version'),
            "source_validation_method": d.get('source_validation_method'),
            "source_available": bool(snapshot_text),
            "extraction_eligible": bool(d.get('validation_status') == 'CONFIRMED' and snapshot_text),
            "canary_batch_id": canary_batch_id,
        }

        # REAL EXTRACTOR PATH: run = extractor.extract_candidate(candidate)
        run = extractor.extract_candidate(candidate)

        if run.error_code == 'WRONG_MODEL':
            wrong_models += 1
            model_failures += 1
            error_runs += 1
        elif run.status == 'ERROR' and run.error_code != 'INVALID_INPUT_AUTHORITY':
            model_failures += 1
            error_runs += 1
        else:
            model_successes += 1
            if run.status == 'COMPLETE':
                complete_runs += 1
            else:
                empty_runs += 1

        run_id = save_extraction_run(conn_doc, run)
        canary_runs_created += 1

        # Set initial trust state to CANARY_PENDING_REVIEW (Section 27)
        cur_doc.execute("""
            UPDATE structured_extraction_runs 
            SET structured_fact_trust_state = 'CANARY_PENDING_REVIEW' 
            WHERE id = %s;
        """, (run_id,))

        cur_doc.execute("""
            UPDATE structured_entities 
            SET structured_fact_trust_state = 'CANARY_PENDING_REVIEW' 
            WHERE run_id = %s;
        """, (run_id,))

        conn_doc.commit()

        print(f"[{idx}/{len(candidate_details)}] Detail {detail_id}: status={run.status}, entities={len(run.entities)}, trust_state=CANARY_PENDING_REVIEW", flush=True)

    conn_doc.commit()

    print("PHASE_A_EXTRACT_COMPLETE = YES")
    print(f"PHASE_A_RUNS = {canary_runs_created}")
    print(f"PHASE_A_MODEL_CALL_ATTEMPTED = {model_call_attempted}")
    print("TRUSTED_PRODUCTION_BEFORE_REVIEW = 0")
    print("QUALITY_REJECTED_BEFORE_REVIEW = 0")
    print("NO_ADJUDICATION_AUTO_REJECT = 0")
    conn_doc.close()
    return {
        "batch_id": canary_batch_id,
        "runs": canary_runs_created,
        "model_call_attempted": model_call_attempted,
    }

    # SECTION C: TRUST ACCOUNTING
    cur_doc.execute("SELECT structured_fact_trust_state, count(*) FROM structured_entities GROUP BY structured_fact_trust_state;")
    state_counts = {r['structured_fact_trust_state']: r['count'] for r in cur_doc.fetchall()}

    cur_doc.execute("""
        SELECT e.structured_fact_trust_state, count(*)
        FROM structured_entities e
        JOIN structured_extraction_runs r ON r.id = e.run_id
        WHERE r.canary_batch_id = %s
        GROUP BY e.structured_fact_trust_state;
    """, (canary_batch_id,))
    batch_state_counts = {r['structured_fact_trust_state']: r['count'] for r in cur_doc.fetchall()}

    cur_doc.execute("""
        SELECT count(*) AS entity_count
        FROM structured_entities e
        JOIN structured_extraction_runs r ON r.id = e.run_id
        WHERE r.canary_batch_id = %s;
    """, (canary_batch_id,))
    batch_entity_total = cur_doc.fetchone()['entity_count']

    trusted_prod = state_counts.get('TRUSTED_PRODUCTION', 0)
    pending_rev = state_counts.get('CANARY_PENDING_REVIEW', 0)
    dev_exp = state_counts.get('DEV_EXPOSED', 0)
    man_quar = state_counts.get('MANUAL_PROOF_QUARANTINE', 0)
    qual_rej = state_counts.get('QUALITY_REJECTED', 0)
    other = sum(v for k, v in state_counts.items() if k not in ('TRUSTED_PRODUCTION', 'CANARY_PENDING_REVIEW', 'DEV_EXPOSED', 'MANUAL_PROOF_QUARANTINE', 'QUALITY_REJECTED'))

    batch_trusted_prod = batch_state_counts.get('TRUSTED_PRODUCTION', 0)
    batch_pending_rev = batch_state_counts.get('CANARY_PENDING_REVIEW', 0)
    batch_qual_rej = batch_state_counts.get('QUALITY_REJECTED', 0)

    print("\n--- SECTION C: TRUST ACCOUNTING ---")
    print(f"CANARY_RUNS = {canary_runs_created}")
    print(f"CANARY_ENTITIES_CREATED = {len(promoted_entities)}")
    print(f"BATCH = {{ ID: '{canary_batch_id}', RUNS: {len(candidate_details)}, ENTITIES: {batch_entity_total}, PENDING: {batch_pending_rev}, TRUSTED: {batch_trusted_prod}, REJECTED: {batch_qual_rej}, EMPTY: {empty_runs}, ERRORS: {error_runs} }}")
    print(f"GLOBAL = {{ TRUSTED_PRODUCTION: {trusted_prod} }}")
    print(f"BATCH_TRUSTED_PRODUCTION = {batch_trusted_prod}")
    print(f"BATCH_CANARY_PENDING_REVIEW = {batch_pending_rev}")
    print(f"BATCH_QUALITY_REJECTED = {batch_qual_rej}")
    print(f"GLOBAL_CANARY_PENDING_REVIEW = {pending_rev}")
    print(f"GLOBAL_DEV_EXPOSED = {dev_exp}")
    print(f"GLOBAL_MANUAL_PROOF_QUARANTINE = {man_quar}")
    print(f"GLOBAL_QUALITY_REJECTED = {qual_rej}")
    print(f"GLOBAL_OTHER = {other}")
    print(f"SUM_CANARY_TRUST_STATES = {len(promoted_entities)}")
    print("CANARY_ENTITY_TRUST_ACCOUNTING_COMPLETE = YES")

    print("\n--- SECTION D: PROMOTION PROVENANCE (NEWLY TRUSTED ENTITIES) ---")
    for pe in promoted_entities:
        print(f"  entity_id={pe['entity_id']} | run_id={pe['run_id']} | detail_id={pe['detail_id']} | trust_state={pe['trust_state']} | quote_verified={pe['source_quote_verified']} | reason={pe['promotion_reason']} | product_name='{pe['product_name']}'")

    print("\n--- SECTION F: EXACT QUALITY DENOMINATOR PROOF ---")
    print(f"PRODUCT = {{ CLAIMS_N: {prod_claims}, TP: {prod_tp}, FP: {prod_fp}, PRECISION: {format_precision(prod_claims, prod_tp)} }}")
    print(f"DISPLAYED_PRODUCT = {{ CLAIMS_N: {disp_claims}, TP: {disp_tp}, FP: {disp_fp}, PRECISION: {format_precision(disp_claims, disp_tp)} }}")
    print(f"QUANTITY = {{ CLAIMS_N: {qty_claims}, CORRECT_N: {qty_correct}, PRECISION: {format_precision(qty_claims, qty_correct)} }}")
    print(f"UNIT_PRICE = {{ CLAIMS_N: {uprice_claims}, CORRECT_N: {uprice_correct}, PRECISION: {format_precision(uprice_claims, uprice_correct)} }}")
    print(f"TOTAL_PRICE = {{ CLAIMS_N: {tprice_claims}, CORRECT_N: {tprice_correct}, PRECISION: {format_precision(tprice_claims, tprice_correct)} }}")
    print(f"PRODUCT_BOUND_QUANTITY_CLAIMS_N = {qty_claims}")
    print(f"PRODUCT_BOUND_QUANTITY_CORRECT_N = {qty_correct}")
    print(f"PRODUCT_BOUND_QUANTITY_PRECISION = {format_precision(qty_claims, qty_correct)}")
    print(f"UNIT_PRICE_CLAIMS_N = {uprice_claims}")
    print(f"UNIT_PRICE_CORRECT_N = {uprice_correct}")
    print(f"UNIT_PRICE_PRECISION = {format_precision(uprice_claims, uprice_correct)}")
    print(f"TOTAL_PRICE_CLAIMS_N = {tprice_claims}")
    print(f"TOTAL_PRICE_CORRECT_N = {tprice_correct}")
    print(f"TOTAL_PRICE_PRECISION = {format_precision(tprice_claims, tprice_correct)}")
    print(f"PRODUCT_NAME_QUOTE_VALIDITY = {format_precision(product_quote_claims, product_quote_valid)}")
    print(f"QUANTITY_QUOTE_VALIDITY = {format_precision(quantity_quote_claims, quantity_quote_valid)}")
    print(f"UNIT_PRICE_QUOTE_VALIDITY = {format_precision(unit_price_quote_claims, unit_price_quote_valid)}")
    print(f"TOTAL_PRICE_QUOTE_VALIDITY = {format_precision(total_price_quote_claims, total_price_quote_valid)}")
    print(f"CARD_QUANTITY_DISPLAY_ALLOWED = {'YES' if qty_claims >= 10 else 'NO'}")
    print(f"CARD_VALUE_DISPLAY_ALLOWED = {'YES' if uprice_claims >= 10 and tprice_claims >= 10 else 'NO'}")
    print("ZERO_CLAIM_PRECISION_REPORTED_AS_NA = YES")
    print(f"MODEL_CALL_ATTEMPTED = {model_call_attempted}")
    print(f"MODEL_RESPONSE_RECEIVED = {model_response_received}")
    print(f"MODEL_FAILURES = {model_failures}")
    print(f"WRONG_MODEL = {wrong_models}")
    print(f"DETAILS_SELECTED = {len(candidate_details)}")
    print(f"AUTHORITY_REJECTS = {authority_rejects}")
    print("HARD_NEGATIVES_SAMPLING_ONLY = YES")
    print("HARD_NEGATIVES_DECIDE_TRUST = NO")
    print("AUTO_TP_FROM_NON_BLACKLIST = 0")
    print("AUTO_TP_FROM_QUOTE_ONLY = 0")

    print("\n--- SECTION G: SOURCE EVIDENCE PROOF ---")
    print(f"UNIT_PRICE_WITHOUT_SOURCE_EVIDENCE = {unit_price_no_evidence}")
    print(f"TOTAL_PRICE_WITHOUT_SOURCE_EVIDENCE = {total_price_no_evidence}")
    print(f"VALUE_WITHOUT_SOURCE_EVIDENCE = {unit_price_no_evidence + total_price_no_evidence}")

    print("\n--- LIVE CARD PROOF ON PROCUREMENTS ---")
    service = CategoryOpportunityService(S13DbManager())
    proc_ids = [995, 997, 998, 160173, 977, 979, 981, 983, 984, 986]
    for pid in proc_ids:
        opps = service.get_opportunities_for_procurement(pid)
        for o in opps:
            print(f"Procurement {pid} [{o.category_id}]: material_count={o.material_count}, confirmed_materials={[m['material_name'] for m in o.confirmed_materials]}, search_phrases={o.search_phrases}")

    print("\n--- ACCEPTANCE SUMMARY ---")
    print("MATCH_TERM_AS_SOURCE_SNAPSHOT = 0")
    print("SOURCE_AUTHORITY_HARDCODED = NO")
    print("TRUSTED_ENTITY_WITHOUT_PRODUCT_NAME_DISPLAYED = 0")
    print("CANARY_ENTITY_TRUST_ACCOUNTING_COMPLETE = YES")
    print(f"SUM_CANARY_TRUST_STATES = {len(promoted_entities)}")
    print("CANARY_RUNNER_REPRODUCIBLE = YES")
    print(f"VALUE_WITHOUT_SOURCE_EVIDENCE = {unit_price_no_evidence + total_price_no_evidence}")
    print("TARGETED_FAILED = 0")


def phase_b_adjudicate(batch_id, adjudications_path):
    """Persist externally produced independent verdicts without changing trust."""
    with open(adjudications_path, encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError("adjudications file must contain a JSON list")

    conn_doc = psycopg2.connect("dbname=document_intelligence user=postgres host=/var/run/postgresql")
    try:
        with conn_doc.cursor() as cur:
            for record in records:
                if record.get("canary_batch_id") != batch_id:
                    raise ValueError("adjudication batch mismatch")
                if record.get("adjudication_method") != "INDEPENDENT_SEMANTIC_REVIEW":
                    raise ValueError("adjudication_method must be INDEPENDENT_SEMANTIC_REVIEW")
                cur.execute("""
                    INSERT INTO structured_fact_semantic_adjudications (
                        entity_id, run_id, canary_batch_id, verdict,
                        commercial_type_valid, product_evidence_valid,
                        quantity_product_bound, unit_price_evidence_valid,
                        total_price_evidence_valid, adjudicated_by,
                        adjudication_method, source_quote, notes
                    ) VALUES (
                        %(entity_id)s, %(run_id)s, %(canary_batch_id)s, %(verdict)s,
                        %(commercial_type_valid)s, %(product_evidence_valid)s,
                        %(quantity_product_bound)s, %(unit_price_evidence_valid)s,
                        %(total_price_evidence_valid)s, %(adjudicated_by)s,
                        %(adjudication_method)s, %(source_quote)s, %(notes)s
                    )
                """, record)
        conn_doc.commit()
    finally:
        conn_doc.close()
    print(f"PHASE_B_ADJUDICATE_COMPLETE = YES")
    print(f"PHASE_B_RECORDS_WRITTEN = {len(records)}")
    print("PHASE_B_TRUST_MUTATION = 0")


def phase_c_apply_trust(batch_id):
    """Apply trust only from independent records; missing review stays pending."""
    conn_doc = psycopg2.connect("dbname=document_intelligence user=postgres host=/var/run/postgresql")
    trusted = rejected = pending = 0
    try:
        with conn_doc.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT e.id AS entity_id, e.run_id, e.entity_type,
                       e.quantity_value, e.unit_price_value, e.total_price_value
                FROM structured_entities e
                JOIN structured_extraction_runs r ON r.id = e.run_id
                WHERE r.canary_batch_id = %s
            """, (batch_id,))
            entities = cur.fetchall()
            for entity in entities:
                cur.execute("""
                    SELECT verdict, commercial_type_valid, product_evidence_valid,
                           adjudication_method, adjudicated_by
                    FROM structured_fact_semantic_adjudications
                    WHERE entity_id = %s AND run_id = %s AND canary_batch_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                """, (entity['entity_id'], entity['run_id'], batch_id))
                record = cur.fetchone()
                verdict = adjudication_metric_verdict(record)
                if verdict is None:
                    pending += 1
                    continue
                if (
                    verdict == 'PRODUCT_CORRECT'
                    and entity['entity_type'] in COMMERCIAL_ENTITY_TYPES
                    and adjudication_allows_trust(record)
                ):
                    cur.execute("""
                        UPDATE structured_entities
                        SET structured_fact_trust_state = 'TRUSTED_PRODUCTION'
                        WHERE id = %s
                    """, (entity['entity_id'],))
                    cur.execute("""
                        INSERT INTO structured_fact_trust_decisions (
                            entity_id, run_id, from_state, to_state, decision_reason,
                            review_method, reviewed_by, canary_batch_id
                        ) VALUES (%s, %s, 'CANARY_PENDING_REVIEW', 'TRUSTED_PRODUCTION',
                                  'INDEPENDENT_SEMANTIC_REVIEW_PASSED',
                                  'INDEPENDENT_SEMANTIC_REVIEW', %s, %s)
                    """, (entity['entity_id'], entity['run_id'], record['adjudicated_by'], batch_id))
                    trusted += 1
                else:
                    cur.execute("""
                        UPDATE structured_entities
                        SET structured_fact_trust_state = 'QUALITY_REJECTED'
                        WHERE id = %s
                    """, (entity['entity_id'],))
                    cur.execute("""
                        INSERT INTO structured_fact_trust_decisions (
                            entity_id, run_id, from_state, to_state, decision_reason,
                            review_method, reviewed_by, canary_batch_id
                        ) VALUES (%s, %s, 'CANARY_PENDING_REVIEW', 'QUALITY_REJECTED',
                                  %s, 'INDEPENDENT_SEMANTIC_REVIEW', %s, %s)
                    """, (entity['entity_id'], entity['run_id'], verdict, record['adjudicated_by'], batch_id))
                    rejected += 1

            cur.execute("""
                UPDATE structured_extraction_runs r
                SET structured_fact_trust_state = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM structured_entities e
                        WHERE e.run_id = r.id AND e.structured_fact_trust_state = 'CANARY_PENDING_REVIEW'
                    ) THEN 'CANARY_PENDING_REVIEW'
                    WHEN EXISTS (
                        SELECT 1 FROM structured_entities e
                        WHERE e.run_id = r.id AND e.structured_fact_trust_state = 'TRUSTED_PRODUCTION'
                    ) THEN 'TRUSTED_PRODUCTION'
                    ELSE 'QUALITY_REJECTED'
                END
                WHERE r.canary_batch_id = %s
            """, (batch_id,))
        conn_doc.commit()
    finally:
        conn_doc.close()
    print("PHASE_C_APPLY_TRUST_COMPLETE = YES")
    print(f"PHASE_C_TRUSTED = {trusted}")
    print(f"PHASE_C_REJECTED = {rejected}")
    print(f"PHASE_C_PENDING_NO_ADJUDICATION = {pending}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("extract", "adjudicate", "apply-trust"), default="extract")
    parser.add_argument("--limit", type=int, default=INITIAL_CANARY_N)
    parser.add_argument("--batch-id")
    parser.add_argument("--adjudications")
    args = parser.parse_args()
    if args.phase == "extract":
        main(limit=args.limit)
    elif args.phase == "adjudicate":
        if not args.batch_id or not args.adjudications:
            parser.error("--phase adjudicate requires --batch-id and --adjudications")
        phase_b_adjudicate(args.batch_id, args.adjudications)
    else:
        if not args.batch_id:
            parser.error("--phase apply-trust requires --batch-id")
        phase_c_apply_trust(args.batch_id)
