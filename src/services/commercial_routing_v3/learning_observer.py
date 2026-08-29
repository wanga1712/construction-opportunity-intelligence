"""CRM V3 Learning Observer Daemon (v3_real_truth)

Responsibilities:
- Enrich queue identity and generation hash
- Build immutable pre-research blind snapshots (STRICT allowlist: source metadata + real canonical document manifest)
- Create exhaustive ground truth ONLY when per-document terminal states are evaluated from document_files LEFT JOIN document_processing_results by source_document_id
- Enforce temporal order: PREDICTION_CREATED_AT < TRUTH_CREATED_AT and TRUTH_CREATED_AT >= LAST_PARSE_TERMINAL_AT
- Exact document classification:
  - USEFUL: download successful AND parse successful AND current-generation evidence linked.
  - NO_TARGET_EVIDENCE: download successful AND parse successful AND zero current-generation evidence.
  - UNKNOWN: download failure, parse failure, unsupported format, unreadable, missing row, missing parse result, incomplete.
- Procurement truth:
  - USEFUL > 0 and UNKNOWN == 0 -> has_target_evidence=YES, truth_completeness=COMPLETE
  - USEFUL > 0 and UNKNOWN > 0 -> has_target_evidence=YES, truth_completeness=PARTIAL
  - USEFUL == 0 and UNKNOWN == 0 -> has_target_evidence=NO, truth_completeness=COMPLETE
  - USEFUL == 0 and UNKNOWN > 0 -> has_target_evidence=UNKNOWN, truth_completeness=PARTIAL
- Producer version: v3_real_truth
"""

import os
import sys
import json
import time
import hashlib
import psycopg2
import psycopg2.extras
from typing import Dict, Any, List, Optional, Tuple

PRODUCER_VERSION = "v3_real_truth"
PIPELINE_GENERATION = "S13_V2"

def get_doc_db():
    user = os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker")
    password = os.environ.get("S13_DOCUMENT_DB_PASSWORD")
    if not password:
        raise RuntimeError("Missing required environment variable S13_DOCUMENT_DB_PASSWORD")
    host = os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1")
    port = os.environ.get("S13_DOCUMENT_DB_PORT", "5432")
    return psycopg2.connect(dbname="document_intelligence", user=user, password=password, host=host, port=port)

def get_crm_db():
    user = os.environ.get("CRM_DB_USER", "crm_app")
    password = os.environ.get("CRM_DB_PASSWORD")
    if not password:
        raise RuntimeError("Missing required environment variable CRM_DB_PASSWORD")
    host = os.environ.get("CRM_DB_HOST", "127.0.0.1")
    port = os.environ.get("CRM_DB_PORT", "5432")
    return psycopg2.connect(dbname="crm", user=user, password=password, host=host, port=port)

def compute_sha256(val: Any) -> str:
    if isinstance(val, (dict, list)):
        s = json.dumps(val, sort_keys=True, ensure_ascii=False)
    else:
        s = str(val or "")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

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
        
        processed["snapshots_created"] = self._build_missing_snapshots()
        processed["truths_created"] = self._build_missing_truths()
        processed["evaluations_created"] = self._evaluate_predictions()
        processed["examples_created"] = self._materialize_examples()

        return processed

    def _build_missing_snapshots(self) -> int:
        doc_conn = get_doc_db()
        crm_conn = get_crm_db()
        created_count = 0
        try:
            with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as q_cur:
                q_cur.execute("""
                    SELECT id, procurement_id, queue_lane, priority_score, research_generation_hash, created_at
                    FROM document_processing_queue
                    WHERE pipeline_generation = %s
                    ORDER BY id DESC LIMIT 500
                """, (PIPELINE_GENERATION,))
                queue_items = q_cur.fetchall()

            for item in queue_items:
                pid = item["procurement_id"]
                gen_hash = item["research_generation_hash"] or compute_sha256(pid)
                qid = item["id"]

                with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c_cur:
                    c_cur.execute("""
                        SELECT id FROM crm_v3_pre_research_snapshots
                        WHERE procurement_id = %s AND research_generation_hash = %s AND producer_version = %s
                    """, (pid, gen_hash, PRODUCER_VERSION))
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

                    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as d_cur:
                        d_cur.execute("""
                            SELECT id, url, file_name, content_type
                            FROM document_files
                            WHERE procurement_id = %s
                        """, (pid,))
                        doc_rows = d_cur.fetchall()

                    document_manifest = []
                    for d in doc_rows:
                        fn = d.get("file_name") or ""
                        ext = fn.split(".")[-1] if "." in fn else "pdf"
                        document_manifest.append({
                            "source_document_id": d["id"],
                            "document_key": f"doc_{pid}_{d['id']}",
                            "document_name": fn or f"document_{d['id']}",
                            "source_url": d.get("url"),
                            "extension": ext
                        })

                    snap_payload = {
                        "source": source_snapshot,
                        "manifest": document_manifest
                    }
                    snap_sha = compute_sha256(snap_payload)

                    c_cur.execute("""
                        INSERT INTO crm_v3_pre_research_snapshots (
                            procurement_id, queue_id, pipeline_generation, research_generation_hash,
                            source_snapshot_json, document_manifest_json, snapshot_sha256, snapshot_schema_version,
                            producer_version, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'v2_canonical_manifest', %s, NOW())
                        ON CONFLICT (procurement_id, research_generation_hash, producer_version) DO NOTHING
                        RETURNING id
                    """, (
                        pid, qid, PIPELINE_GENERATION, gen_hash,
                        json.dumps(source_snapshot), json.dumps(document_manifest), snap_sha, PRODUCER_VERSION
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
        doc_conn = get_doc_db()
        crm_conn = get_crm_db()
        created_count = 0
        try:
            with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, procurement_id, queue_lane, priority_score, status, research_generation_hash, completed_at
                    FROM document_processing_queue
                    WHERE pipeline_generation = %s AND status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
                    ORDER BY id DESC LIMIT 500
                """, (PIPELINE_GENERATION,))
                term_items = cur.fetchall()

            for item in term_items:
                pid = item["procurement_id"]
                gen_hash = item["research_generation_hash"] or compute_sha256(pid)
                qid = item["id"]

                with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c_cur:
                    c_cur.execute("""
                        SELECT id FROM crm_v3_exhaustive_truth
                        WHERE procurement_id = %s AND research_generation_hash = %s AND producer_version = %s
                    """, (pid, gen_hash, PRODUCER_VERSION))
                    if c_cur.fetchone():
                        continue

                    c_cur.execute("""
                        SELECT document_manifest_json FROM crm_v3_pre_research_snapshots
                        WHERE procurement_id = %s AND research_generation_hash = %s AND producer_version = %s
                    """, (pid, gen_hash, PRODUCER_VERSION))
                    snap_row = c_cur.fetchone()
                    if not snap_row:
                        continue

                    manifest = snap_row["document_manifest_json"]
                    if isinstance(manifest, str):
                        manifest = json.loads(manifest)

                    # Inspect document_files LEFT JOIN document_processing_results by source_document_id
                    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as d_cur:
                        d_cur.execute("""
                            SELECT f.id as source_document_id, f.download_status, f.downloaded_at, f.created_at as file_created_at,
                                   r.status as parse_status, r.completed_at as parse_completed_at
                            FROM document_files f
                            LEFT JOIN document_processing_results r ON f.id = r.file_id
                            WHERE f.procurement_id = %s
                        """, (pid,))
                        doc_results = d_cur.fetchall()

                    doc_map = {dr["source_document_id"]: dr for dr in doc_results}

                    # Query STRICT current-generation evidence
                    c_cur.execute("""
                        SELECT source_document_id FROM crm_v3_raw_source_evidence
                        WHERE procurement_id = %s AND pipeline_generation = %s AND research_generation_hash = %s
                    """, (pid, PIPELINE_GENERATION, gen_hash))
                    ev_rows = c_cur.fetchall()

                    ev_doc_ids = set()
                    for ev in ev_rows:
                        if ev.get("source_document_id"):
                            ev_doc_ids.add(ev["source_document_id"])

                    useful_docs = []
                    non_useful_docs = []
                    unknown_docs = []
                    max_parse_at = item["completed_at"]

                    for d in manifest:
                        d_id = d.get("source_document_id")
                        d_key = d.get("document_key")
                        d_item = {"document_key": d_key, "source_document_id": d_id, "document_name": d.get("document_name")}

                        dr = doc_map.get(d_id)
                        if not dr:
                            # Missing document row -> UNKNOWN
                            unknown_docs.append(d_item)
                            continue

                        dl_st = str(dr.get("download_status") or "").upper()
                        pr_st = str(dr.get("parse_status") or "").upper() if dr.get("parse_status") else None
                        p_at = dr.get("parse_completed_at") or dr.get("downloaded_at") or dr.get("file_created_at")

                        if p_at and (max_parse_at is None or p_at > max_parse_at):
                            max_parse_at = p_at

                        if dl_st == "COMPLETED" and pr_st == "COMPLETED":
                            if d_id and d_id in ev_doc_ids:
                                useful_docs.append(d_item)
                            else:
                                non_useful_docs.append(d_item)
                        else:
                            # Any failure/unsupported/unreadable/missing parse result -> UNKNOWN
                            unknown_docs.append(d_item)

                    docs_total = len(manifest)
                    useful_cnt = len(useful_docs)
                    no_target_cnt = len(non_useful_docs)
                    unknown_cnt = len(unknown_docs)

                    if useful_cnt > 0 and unknown_cnt == 0:
                        has_target = "YES"
                        truth_completeness = "COMPLETE"
                    elif useful_cnt > 0 and unknown_cnt > 0:
                        has_target = "YES"
                        truth_completeness = "PARTIAL"
                    elif useful_cnt == 0 and unknown_cnt == 0:
                        has_target = "NO"
                        truth_completeness = "COMPLETE"
                    else:  # useful_cnt == 0 and unknown_cnt > 0
                        has_target = "UNKNOWN"
                        truth_completeness = "PARTIAL"

                    c_cur.execute("""
                        INSERT INTO crm_v3_exhaustive_truth (
                            procurement_id, queue_id, pipeline_generation, research_generation_hash,
                            documents_total, documents_terminal_supported, documents_failed_or_unknown,
                            has_target_evidence, useful_documents_json, non_useful_documents_json,
                            unknown_documents_json, evidence_count, truth_completeness, truth_source,
                            producer_version, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'AUTO_FACT', %s, NOW())
                        ON CONFLICT (procurement_id, research_generation_hash, producer_version) DO NOTHING
                        RETURNING id
                    """, (
                        pid, qid, PIPELINE_GENERATION, gen_hash,
                        docs_total, useful_cnt + no_target_cnt, unknown_cnt,
                        has_target, json.dumps(useful_docs), json.dumps(non_useful_docs), json.dumps(unknown_docs),
                        len(ev_rows), truth_completeness, PRODUCER_VERSION
                    ))
                    res = c_cur.fetchone()
                    if res:
                        created_count += 1
            crm_conn.commit()
        finally:
            doc_conn.close()
            crm_conn.close()
        return created_count

    def _evaluate_predictions(self) -> int:
        crm_conn = get_crm_db()
        eval_count = 0
        try:
            with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Require PREDICTION_CREATED_AT < TRUTH_CREATED_AT (strict temporal order)
                cur.execute("""
                    SELECT p.id as prediction_id, t.id as truth_id, p.procurement_id, p.research_generation_hash,
                           p.has_target_decision, p.document_ranking_json, t.has_target_evidence, t.evidence_count,
                           t.truth_completeness, t.useful_documents_json, t.non_useful_documents_json,
                           p.created_at as pred_at, t.created_at as truth_at
                    FROM crm_v3_shadow_predictions p
                    JOIN crm_v3_exhaustive_truth t 
                      ON p.procurement_id = t.procurement_id 
                     AND p.research_generation_hash = t.research_generation_hash
                    LEFT JOIN crm_v3_shadow_evaluations e ON p.id = e.prediction_id
                    WHERE e.id IS NULL AND p.producer_version = %s AND t.producer_version = %s
                      AND p.created_at < t.created_at
                    LIMIT 500
                """, (PRODUCER_VERSION, PRODUCER_VERSION))
                pairs = cur.fetchall()

                for pair in pairs:
                    if pair["truth_completeness"] != "COMPLETE":
                        continue

                    pred_target = pair["has_target_decision"] == "YES"
                    fact_target = pair["has_target_evidence"] == "YES"
                    false_neg = (not pred_target) and fact_target

                    useful_docs = pair["useful_documents_json"]
                    if isinstance(useful_docs, str):
                        useful_docs = json.loads(useful_docs)
                    useful_keys = {d["document_key"] for d in useful_docs if "document_key" in d}

                    ranking = pair["document_ranking_json"]
                    if isinstance(ranking, str):
                        ranking = json.loads(ranking)

                    if len(useful_keys) > 0 and len(ranking) > 0:
                        ranks = []
                        for item in ranking:
                            d_k = item.get("document_key")
                            r_num = item.get("rank", 1)
                            if d_k in useful_keys:
                                ranks.append(r_num)

                        if ranks:
                            first_rank = min(ranks)
                            mrr = round(1.0 / first_rank, 4)
                            doc_recall_1 = round(sum(1 for r in ranks if r <= 1) / float(len(useful_keys)), 4)
                            doc_recall_3 = round(sum(1 for r in ranks if r <= 3) / float(len(useful_keys)), 4)
                            doc_recall_5 = round(sum(1 for r in ranks if r <= 5) / float(len(useful_keys)), 4)
                            sim_needed = first_rank
                            sim_skipped = sum(1 for item in ranking if item.get("rank", 1) < first_rank and item.get("document_key") not in useful_keys)
                        else:
                            first_rank = None
                            mrr = None
                            doc_recall_1 = 0.0
                            doc_recall_3 = 0.0
                            doc_recall_5 = 0.0
                            sim_needed = len(ranking)
                            sim_skipped = 0
                    else:
                        doc_recall_1 = None
                        doc_recall_3 = None
                        doc_recall_5 = None
                        mrr = None
                        first_rank = None
                        sim_needed = 0
                        sim_skipped = 0

                    error_payload = {
                        "false_negative": false_neg,
                        "pred_decision": pair["has_target_decision"],
                        "fact_evidence": pair["has_target_evidence"],
                        "useful_doc_keys": list(useful_keys)
                    }

                    cur.execute("""
                        INSERT INTO crm_v3_shadow_evaluations (
                            prediction_id, truth_id, procurement_id, research_generation_hash,
                            false_negative, doc_recall_at_1, doc_recall_at_3, doc_recall_at_5,
                            mrr, first_useful_rank, simulated_documents_needed, simulated_documents_skipped,
                            error_json, label_source, producer_version, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'AUTO_FACT', %s, NOW())
                        RETURNING id
                    """, (
                        pair["prediction_id"], pair["truth_id"], pair["procurement_id"], pair["research_generation_hash"],
                        false_neg, doc_recall_1, doc_recall_3, doc_recall_5,
                        mrr, first_rank, sim_needed, sim_skipped, json.dumps(error_payload), PRODUCER_VERSION
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
                           s.procurement_id, s.source_snapshot_json, s.document_manifest_json,
                           t.has_target_evidence, t.useful_documents_json, t.non_useful_documents_json
                    FROM crm_v3_shadow_evaluations e
                    JOIN crm_v3_shadow_predictions p ON e.prediction_id = p.id
                    JOIN crm_v3_pre_research_snapshots s ON p.snapshot_id = s.id
                    JOIN crm_v3_exhaustive_truth t ON e.truth_id = t.id
                    LEFT JOIN crm_v3_learning_examples l ON e.id = l.evaluation_id
                    WHERE l.id IS NULL AND e.producer_version = %s AND t.has_target_evidence IN ('YES', 'NO')
                    LIMIT 500
                """, (PRODUCER_VERSION,))
                rows = cur.fetchall()

                for r in rows:
                    pid = r["procurement_id"]
                    h_val = int(compute_sha256(f"split_{pid}")[:8], 16) % 100
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
                            task_type, input_json, target_json, label_source, sample_weight, dataset_split,
                            producer_version, created_at
                        ) VALUES (%s, %s, %s, %s, 'PROCUREMENT_RELEVANCE', %s, %s, 'AUTO_FACT', 1.0, %s, %s, NOW())
                        RETURNING id
                    """, (
                        r["snapshot_id"], r["prediction_id"], r["truth_id"], r["eval_id"],
                        json.dumps(input_json), json.dumps(target_json), split, PRODUCER_VERSION
                    ))
                    if cur.fetchone():
                        ex_count += 1

                    manifest = r["document_manifest_json"]
                    if isinstance(manifest, str):
                        manifest = json.loads(manifest)

                    if len(manifest) > 0:
                        doc_input_json = {
                            "procurement_metadata": input_json,
                            "document_manifest": manifest
                        }
                        doc_target_json = {
                            "useful_documents": r["useful_documents_json"],
                            "non_useful_documents": r["non_useful_documents_json"]
                        }
                        cur.execute("""
                            INSERT INTO crm_v3_learning_examples (
                                snapshot_id, prediction_id, truth_id, evaluation_id,
                                task_type, input_json, target_json, label_source, sample_weight, dataset_split,
                                producer_version, created_at
                            ) VALUES (%s, %s, %s, %s, 'DOCUMENT_RANKING', %s, %s, 'AUTO_FACT', 1.0, %s, %s, NOW())
                            RETURNING id
                        """, (
                            r["snapshot_id"], r["prediction_id"], r["truth_id"], r["eval_id"],
                            json.dumps(doc_input_json), json.dumps(doc_target_json), split, PRODUCER_VERSION
                        ))
                        if cur.fetchone():
                            ex_count += 1
            crm_conn.commit()
        finally:
            crm_conn.close()
        return ex_count

if __name__ == "__main__":
    observer = LearningObserver()
    print("Starting CRM V3 Learning Observer loop (v3_real_truth)...")
    while True:
        try:
            res = observer.run_cycle()
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Observer error: {e}", file=sys.stderr)
            time.sleep(5)
