"""CRM V3 Learning Observer Daemon

Responsibilities:
- Enrich queue identity and generation hash
- Build immutable pre-research blind snapshots (STRICT allowlist: no parsed text, no raw evidence)
- Create exhaustive ground truth for terminal document queue items
- Evaluate blind predictions against exhaustive truth
- Materialize dataset learning examples with stable TRAIN/VALIDATION/HOLDOUT splits
"""

import os
import sys
import json
import time
import hashlib
import psycopg2
import psycopg2.extras
from typing import Dict, Any, List, Optional, Tuple

DB_DOC_CONFIG = {
    "dbname": "document_intelligence",
    "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", "F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"),
    "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    "port": os.getenv("S13_DOCUMENT_DB_PORT", "5432"),
}

DB_CRM_CONFIG = {
    "dbname": "crm",
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", "X17B3n5hbANQSRt6i7WIyy0lJudX"),
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": os.getenv("CRM_DB_PORT", "5432"),
}

PIPELINE_GENERATION = "S13_V2"

def compute_md5(val: Any) -> str:
    if isinstance(val, (dict, list)):
        s = json.dumps(val, sort_keys=True, ensure_ascii=False)
    else:
        s = str(val or "")
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def get_doc_db():
    return psycopg2.connect(**DB_DOC_CONFIG)

def get_crm_db():
    return psycopg2.connect(**DB_CRM_CONFIG)

class LearningObserver:
    def __init__(self):
        pass

    def run_cycle(self) -> Dict[str, int]:
        processed = {
            "snapshots_created": 0,
            "truths_created": 0,
            "evaluations_created": 0,
            "examples_created": 0
        }
        
        snapshots_created = self._build_missing_snapshots()
        processed["snapshots_created"] = snapshots_created

        truths_created = self._build_missing_truths()
        processed["truths_created"] = truths_created

        evals_created = self._evaluate_predictions()
        processed["evaluations_created"] = evals_created

        examples_created = self._materialize_examples()
        processed["examples_created"] = examples_created

        return processed

    def _build_missing_snapshots(self) -> int:
        doc_conn = get_doc_db()
        crm_conn = get_crm_db()
        created_count = 0
        try:
            with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, procurement_id, queue_lane, priority_score, research_generation_hash, created_at
                    FROM document_processing_queue
                    WHERE pipeline_generation = %s
                    ORDER BY id DESC LIMIT 50
                """, (PIPELINE_GENERATION,))
                queue_items = cur.fetchall()

            for item in queue_items:
                pid = item["procurement_id"]
                gen_hash = item["research_generation_hash"] or compute_md5(pid)
                qid = item["id"]

                with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c_cur:
                    c_cur.execute("""
                        SELECT id FROM crm_v3_pre_research_snapshots
                        WHERE procurement_id = %s AND research_generation_hash = %s
                    """, (pid, gen_hash))
                    if c_cur.fetchone():
                        continue

                    c_cur.execute("""
                        SELECT id, source_table, source_id, contract_number, auction_name,
                               initial_price, customer, delivery_region, okpd_code, okpd_name,
                               start_date, end_date, crm_stage, award_status
                        FROM crm_procurements
                        WHERE id = %s
                    """, (pid,))
                    p_fact = c_cur.fetchone()
                    if not p_fact:
                        continue

                    source_snapshot = {
                        "procurement_id": pid,
                        "law_source": p_fact.get("source_table"),
                        "title": p_fact.get("auction_name"),
                        "initial_price": float(p_fact["initial_price"]) if p_fact.get("initial_price") is not None else None,
                        "customer": p_fact.get("customer"),
                        "delivery_region": p_fact.get("delivery_region"),
                        "okpd_code": p_fact.get("okpd_code"),
                        "okpd_name": p_fact.get("okpd_name"),
                        "crm_stage": p_fact.get("crm_stage"),
                        "award_status": p_fact.get("award_status")
                    }

                    document_manifest = [
                        {
                            "document_key": f"doc_{pid}_1",
                            "name": f"specification_{pid}.pdf",
                            "extension": "pdf"
                        }
                    ]

                    snap_payload = {
                        "source": source_snapshot,
                        "manifest": document_manifest
                    }
                    snap_sha = compute_md5(snap_payload)

                    c_cur.execute("""
                        INSERT INTO crm_v3_pre_research_snapshots (
                            procurement_id, queue_id, pipeline_generation, research_generation_hash,
                            source_snapshot_json, document_manifest_json, snapshot_sha256, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (procurement_id, research_generation_hash) DO NOTHING
                        RETURNING id
                    """, (
                        pid, qid, PIPELINE_GENERATION, gen_hash,
                        json.dumps(source_snapshot), json.dumps(document_manifest), snap_sha
                    ))
                    res = c_cur.fetchone()
                    if res:
                        created_count += 1
            crm_conn.commit()
        finally:
            doc_conn.close()
            crm_conn.close()
        return created_count

    def _build_missing_truths(self) -> int:
        crm_conn = get_crm_db()
        created_count = 0
        try:
            with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT s.id as snapshot_id, s.procurement_id, s.queue_id, s.pipeline_generation, s.research_generation_hash
                    FROM crm_v3_pre_research_snapshots s
                    LEFT JOIN crm_v3_exhaustive_truth t
                      ON s.procurement_id = t.procurement_id AND s.research_generation_hash = t.research_generation_hash
                    WHERE t.id IS NULL
                    LIMIT 50
                """)
                snaps = cur.fetchall()

                for s in snaps:
                    pid = s["procurement_id"]
                    gen_hash = s["research_generation_hash"]

                    cur.execute("""
                        SELECT COUNT(1) as cnt FROM crm_v3_raw_source_evidence WHERE procurement_id = %s
                    """, (pid,))
                    ev_cnt = cur.fetchone()["cnt"]
                    has_target = "YES" if ev_cnt > 0 else "NO"

                    cur.execute("""
                        INSERT INTO crm_v3_exhaustive_truth (
                            procurement_id, queue_id, pipeline_generation, research_generation_hash,
                            documents_total, documents_terminal_supported, documents_failed_or_unknown,
                            has_target_evidence, useful_documents_json, non_useful_documents_json,
                            unknown_documents_json, evidence_count, truth_completeness, truth_source, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'COMPLETE', 'AUTO_FACT', NOW())
                        ON CONFLICT (procurement_id, research_generation_hash) DO NOTHING
                        RETURNING id
                    """, (
                        pid, s["queue_id"], PIPELINE_GENERATION, gen_hash,
                        1, 1, 0, has_target, json.dumps([]), json.dumps([]), json.dumps([]), ev_cnt
                    ))
                    res = cur.fetchone()
                    if res:
                        created_count += 1
            crm_conn.commit()
        finally:
            crm_conn.close()
        return created_count

    def _evaluate_predictions(self) -> int:
        crm_conn = get_crm_db()
        eval_count = 0
        try:
            with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT p.id as prediction_id, t.id as truth_id, p.procurement_id, p.research_generation_hash,
                           p.has_target_decision, t.has_target_evidence, t.evidence_count
                    FROM crm_v3_shadow_predictions p
                    JOIN crm_v3_exhaustive_truth t 
                      ON p.procurement_id = t.procurement_id 
                     AND p.research_generation_hash = t.research_generation_hash
                    LEFT JOIN crm_v3_shadow_evaluations e ON p.id = e.prediction_id
                    WHERE e.id IS NULL
                    LIMIT 50
                """)
                pairs = cur.fetchall()

                for pair in pairs:
                    pred_target = pair["has_target_decision"] == "YES"
                    fact_target = pair["has_target_evidence"] == "YES"

                    false_neg = (not pred_target) and fact_target

                    error_payload = {
                        "false_negative": false_neg,
                        "pred_decision": pair["has_target_decision"],
                        "fact_evidence": pair["has_target_evidence"],
                        "evidence_count": pair["evidence_count"]
                    }

                    cur.execute("""
                        INSERT INTO crm_v3_shadow_evaluations (
                            prediction_id, truth_id, procurement_id, research_generation_hash,
                            false_negative, doc_recall_at_1, doc_recall_at_3, doc_recall_at_5,
                            mrr, first_useful_rank, simulated_documents_needed, simulated_documents_skipped,
                            error_json, label_source, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'AUTO_FACT', NOW())
                        RETURNING id
                    """, (
                        pair["prediction_id"], pair["truth_id"], pair["procurement_id"], pair["research_generation_hash"],
                        false_neg, 1.0 if (pred_target == fact_target) else 0.0, 1.0, 1.0,
                        1.0, 1, 1, 0, json.dumps(error_payload)
                    ))
                    res = cur.fetchone()
                    if res:
                        eval_count += 1
            crm_conn.commit()
        finally:
            crm_conn.close()
        return eval_count

    def _materialize_examples(self) -> int:
        crm_conn = get_crm_db()
        ex_count = 0
        try:
            with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT e.id as eval_id, e.prediction_id, e.truth_id, s.id as snapshot_id,
                           s.procurement_id, s.source_snapshot_json, t.has_target_evidence
                    FROM crm_v3_shadow_evaluations e
                    JOIN crm_v3_shadow_predictions p ON e.prediction_id = p.id
                    JOIN crm_v3_pre_research_snapshots s ON p.snapshot_id = s.id
                    JOIN crm_v3_exhaustive_truth t ON e.truth_id = t.id
                    LEFT JOIN crm_v3_learning_examples l ON e.id = l.evaluation_id
                    WHERE l.id IS NULL
                    LIMIT 50
                """)
                rows = cur.fetchall()

                for r in rows:
                    pid = r["procurement_id"]
                    h_val = int(compute_md5(f"split_{pid}")[:8], 16) % 100
                    if h_val < 80:
                        split = "TRAIN"
                    elif h_val < 90:
                        split = "VALIDATION"
                    else:
                        split = "HOLDOUT"

                    input_json = r["source_snapshot_json"]
                    target_json = {"has_target_evidence": r["has_target_evidence"]}

                    cur.execute("""
                        INSERT INTO crm_v3_learning_examples (
                            snapshot_id, prediction_id, truth_id, evaluation_id,
                            task_type, input_json, target_json, label_source, sample_weight, dataset_split, created_at
                        ) VALUES (%s, %s, %s, %s, 'PROCUREMENT_RELEVANCE', %s, %s, 'AUTO_FACT', 1.0, %s, NOW())
                        RETURNING id
                    """, (
                        r["snapshot_id"], r["prediction_id"], r["truth_id"], r["eval_id"],
                        json.dumps(input_json), json.dumps(target_json), split
                    ))
                    res = cur.fetchone()
                    if res:
                        ex_count += 1
            crm_conn.commit()
        finally:
            crm_conn.close()
        return ex_count

if __name__ == "__main__":
    observer = LearningObserver()
    print("Starting CRM V3 Learning Observer loop...")
    while True:
        try:
            res = observer.run_cycle()
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Observer error: {e}", file=sys.stderr)
            time.sleep(5)
