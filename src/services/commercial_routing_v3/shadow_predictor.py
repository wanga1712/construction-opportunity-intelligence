"""CRM V3 Shadow Predictor Daemon (v3_real_truth)

Responsibilities:
- Select unpredicted blind pre-research snapshot
- Run Qwen2.5:7b with v3_pre_research_shadow_v1 prompt schema
- Include BOTH source_snapshot_json AND document_manifest_json in prompt (no parsed text/evidence)
- Respect shared GPU lock (acquire_gpu_inference) and yield to Hunter/Auditor foreground tasks
- Query active canonical categories from crm_product_categories (category_code, is_active=True). FAIL validation if empty.
- Perform STRICT schema validation of model response (JSON keys, active categories, manifest keys, rank uniqueness)
- Record parse/validation status truthfully in crm_v3_model_inference_runs (run_status = PARSED_SCHEMA_INVALID on invalid output)
- DO NOT insert shadow prediction on invalid model output (NO fabricated fallbacks)
- Producer version: v3_real_truth
"""

import os
import sys
import json
import time
import hashlib
import requests
import psycopg2
import psycopg2.extras
from typing import Dict, Any, List, Optional, Set

from src.services.commercial_routing_v3.gpu_arbiter import (
    acquire_gpu_inference,
    should_defer_document,
    WORKLOAD_DOCUMENT,
)

PRODUCER_VERSION = "v3_real_truth"
PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
BASE_MODEL = "qwen2.5:7b"
PROMPT_VERSION = "v3_pre_research_shadow_v1"

VALID_DECISIONS = {"YES", "NO", "UNCERTAIN"}
VALID_PRIORITIES = {"GOLD_CANDIDATE", "SILVER_CANDIDATE", "BRONZE_CANDIDATE", "LOW_PRIORITY", "UNSCORED"}

def compute_sha256(val: Any) -> str:
    if isinstance(val, (dict, list)):
        s = json.dumps(val, sort_keys=True, ensure_ascii=False)
    else:
        s = str(val or "")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def get_crm_db():
    user = os.environ.get("CRM_DB_USER", "crm_app")
    password = os.environ.get("CRM_DB_PASSWORD")
    if not password:
        raise RuntimeError("Missing required environment variable CRM_DB_PASSWORD")
    host = os.environ.get("CRM_DB_HOST", "127.0.0.1")
    port = os.environ.get("CRM_DB_PORT", "5432")
    return psycopg2.connect(dbname="crm", user=user, password=password, host=host, port=port)

def get_doc_db():
    user = os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker")
    password = os.environ.get("S13_DOCUMENT_DB_PASSWORD")
    if not password:
        raise RuntimeError("Missing required environment variable S13_DOCUMENT_DB_PASSWORD")
    host = os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1")
    port = os.environ.get("S13_DOCUMENT_DB_PORT", "5432")
    return psycopg2.connect(dbname="document_intelligence", user=user, password=password, host=host, port=port)


def fetch_active_categories(crm_conn) -> Optional[Set[str]]:
    """Query active category codes from crm_product_categories. Return None on failure/empty."""
    try:
        with crm_conn.cursor() as cur:
            cur.execute("SELECT category_code FROM crm_product_categories WHERE is_active = True")
            cats = {r[0] for r in cur.fetchall() if r[0]}
            return cats if cats else None
    except Exception:
        return None

def validate_shadow_output(parsed: Any, manifest: List[Dict[str, Any]], active_cats: Optional[Set[str]]) -> bool:
    if not active_cats:
        return False

    if not isinstance(parsed, dict):
        return False

    if "has_target_probability" not in parsed or "has_target_decision" not in parsed:
        return False
    if "priority_candidate" not in parsed or "overall_confidence" not in parsed:
        return False

    try:
        prob = float(parsed["has_target_probability"])
        if not (0.0 <= prob <= 1.0):
            return False
        
        conf = float(parsed["overall_confidence"])
        if not (0.0 <= conf <= 1.0):
            return False
    except (ValueError, TypeError):
        return False

    decision = str(parsed["has_target_decision"]).upper()
    if decision not in VALID_DECISIONS:
        return False

    priority = str(parsed["priority_candidate"]).upper()
    if priority not in VALID_PRIORITIES:
        return False

    cats = parsed.get("predicted_categories")
    if not isinstance(cats, list):
        return False

    for c in cats:
        if not isinstance(c, dict) or "category_code" not in c or "confidence" not in c:
            return False
        code = str(c["category_code"])
        if code not in active_cats:
            return False
        try:
            c_conf = float(c["confidence"])
            if not (0.0 <= c_conf <= 1.0):
                return False
        except (ValueError, TypeError):
            return False

    ranking = parsed.get("document_ranking")
    if not isinstance(ranking, list):
        return False

    manifest_keys = {d["document_key"] for d in manifest if "document_key" in d}
    seen_keys = set()
    seen_ranks = set()

    for item in ranking:
        if not isinstance(item, dict) or "document_key" not in item or "rank" not in item or "useful_evidence_probability" not in item:
            return False
        
        d_key = str(item["document_key"])
        if manifest_keys and d_key not in manifest_keys:
            return False
        if d_key in seen_keys:
            return False
        seen_keys.add(d_key)

        try:
            r_num = int(item["rank"])
            if r_num < 1:
                return False
            if r_num in seen_ranks:
                return False
            seen_ranks.add(r_num)

            p_val = float(item["useful_evidence_probability"])
            if not (0.0 <= p_val <= 1.0):
                return False
        except (ValueError, TypeError):
            return False

    return True

def release_pre_research_queue(
    queue_id: int,
    procurement_id: int,
    pipeline_generation: str,
    research_generation_hash: str,
    outcome: str,
    category_context: Optional[Dict[str, Any]] = None
) -> None:
    """Explicitly releases a queue row from PRE_RESEARCH_WAITING to PENDING.
    
    If outcome is 'SUCCESS', marks learning_sample_mode = 'ONLINE_CLEAN'.
    If outcome is 'FAILED', marks learning_sample_mode = 'BACKFILL_FACT_ONLY'.
    Otherwise, does nothing (waits for retry).
    """
    if outcome not in ("SUCCESS", "FAILED"):
        return

    context = dict(category_context or {})
    if outcome == "SUCCESS":
        context["learning_sample_mode"] = "ONLINE_CLEAN"
        context["blind_prediction_status"] = "SUCCESS"
    else:
        context["learning_sample_mode"] = "BACKFILL_FACT_ONLY"
        context["blind_prediction_status"] = "FAILED"

    doc_conn = get_doc_db()
    try:
        with doc_conn.cursor() as cur:
            cur.execute("""
                UPDATE document_processing_queue
                SET status = 'PENDING',
                    category_context = %s
                WHERE id = %s 
                  AND procurement_id = %s 
                  AND pipeline_generation = %s 
                  AND (
                      research_generation_hash = %s 
                      OR (research_generation_hash IS NULL AND (%s IS NULL OR %s = ''))
                      OR (research_generation_hash = '' AND (%s IS NULL OR %s = ''))
                  )
                  AND status = 'PRE_RESEARCH_WAITING'
            """, (json.dumps(context), queue_id, procurement_id, pipeline_generation, research_generation_hash, research_generation_hash, research_generation_hash, research_generation_hash, research_generation_hash))
        doc_conn.commit()
        print(f"Released queue row {queue_id} (procurement {procurement_id}) to PENDING with mode {context['learning_sample_mode']}")
    except Exception as exc:
        doc_conn.rollback()
        print(f"Failed to release queue row {queue_id} to PENDING: {exc}", file=sys.stderr)
        raise
    finally:
        doc_conn.close()

class ShadowPredictor:
    def __init__(self):
        pass

    def run_cycle(self) -> bool:
        if should_defer_document():
            time.sleep(2)
            return False

        # 1. Fetch exactly one row in PRE_RESEARCH_WAITING from Document DB
        doc_conn = get_doc_db()
        try:
            with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as doc_cur:
                doc_cur.execute("""
                    SELECT id as queue_id, procurement_id, pipeline_generation, research_generation_hash, category_context
                    FROM document_processing_queue
                    WHERE status = 'PRE_RESEARCH_WAITING' AND pipeline_generation = %s
                    ORDER BY id DESC LIMIT 1
                """, (PIPELINE_GENERATION,))
                queue_row = doc_cur.fetchone()
        except Exception as exc:
            print(f"Failed to query queue in Document DB: {exc}", file=sys.stderr)
            return False
        finally:
            doc_conn.close()

        if not queue_row:
            return False

        pid = queue_row["procurement_id"]
        queue_id = queue_row["queue_id"]
        pipeline_generation = queue_row["pipeline_generation"]
        gen_hash = queue_row["research_generation_hash"]
        effective_gen_hash = gen_hash or compute_sha256(pid)
        cat_ctx = queue_row["category_context"]
        if isinstance(cat_ctx, str):
            cat_ctx = json.loads(cat_ctx)

        # 2. Count attempts for this shadow prediction in CRM DB
        crm_conn = get_crm_db()
        try:
            with crm_conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(1) FROM crm_v3_model_inference_runs
                    WHERE procurement_id = %s AND run_kind = 'SHADOW'
                """, (pid,))
                attempts = cur.fetchone()[0]
        except Exception as exc:
            print(f"Failed to query model runs in CRM DB: {exc}", file=sys.stderr)
            crm_conn.close()
            return False

        # 3. If attempts >= 3, release as FAILED (BACKFILL_FACT_ONLY)
        if attempts >= 3:
            print(f"Procurement {pid} shadow prediction attempts reached limit ({attempts}). Releasing as FAILED.")
            crm_conn.close()
            release_pre_research_queue(
                queue_id=queue_id,
                procurement_id=pid,
                pipeline_generation=pipeline_generation,
                research_generation_hash=gen_hash,
                outcome="FAILED",
                category_context=cat_ctx
            )
            return True

        # 4. Fetch the exact matching snapshot from CRM DB
        try:
            active_cats = fetch_active_categories(crm_conn)
            with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id as snapshot_id, procurement_id, research_generation_hash,
                           source_snapshot_json, document_manifest_json, pipeline_generation, queue_id
                    FROM crm_v3_pre_research_snapshots
                    WHERE procurement_id = %s AND pipeline_generation = %s AND research_generation_hash = %s
                    LIMIT 1
                """, (pid, pipeline_generation, effective_gen_hash))
                snap = cur.fetchone()
        except Exception as exc:
            print(f"Failed to query snapshots in CRM DB: {exc}", file=sys.stderr)
            crm_conn.close()
            return False

        if not snap:
            print(f"Snapshot not found for procurement {pid} of generation {gen_hash}. Waiting for snapshot builder.")
            crm_conn.close()
            return False

        source_json = snap["source_snapshot_json"]
        manifest_json = snap["document_manifest_json"]
        if isinstance(source_json, str):
            source_json = json.loads(source_json)
        if isinstance(manifest_json, str):
            manifest_json = json.loads(manifest_json)

        system_prompt = (
            "You are a pre-research shadow predictor for procurement intelligence.\n"
            "Analyze the factual procurement metadata and document manifest.\n"
            "Output ONLY valid JSON matching this schema:\n"
            "{\n"
            '  "has_target_probability": float (0.0 to 1.0),\n'
            '  "has_target_decision": "YES" | "NO" | "UNCERTAIN",\n'
            '  "priority_candidate": "GOLD_CANDIDATE" | "SILVER_CANDIDATE" | "BRONZE_CANDIDATE" | "LOW_PRIORITY" | "UNSCORED",\n'
            '  "predicted_categories": [{"category_code": str, "confidence": float}],\n'
            '  "document_ranking": [{"document_key": str, "rank": int, "useful_evidence_probability": float}],\n'
            '  "overall_confidence": float (0.0 to 1.0)\n'
            "}"
        )
        user_prompt = (
            f"ALLOWED CATEGORIES (you must only use category_code values from this list):\n"
            f"{json.dumps(list(active_cats or []), ensure_ascii=False)}\n\n"
            f"PROCUREMENT SOURCE METADATA:\n{json.dumps(source_json, ensure_ascii=False, indent=2)}\n\n"
            f"DOCUMENT MANIFEST:\n{json.dumps(manifest_json, ensure_ascii=False, indent=2)}"
        )

        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        # 5. Call LLM
        raw_text = None
        run_status = "PENDING"
        try:
            with acquire_gpu_inference(WORKLOAD_DOCUMENT, poll_sec=0.5, max_wait_sec=60.0):
                resp = requests.post(OLLAMA_URL, json={
                    "model": BASE_MODEL,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": 0.1}
                }, timeout=60)
                resp_data = resp.json()
                raw_text = resp_data.get("response", "{}")
                run_status = "SUCCESS"
        except Exception as exc:
            run_status = f"API_FAILED: {exc}"
            raw_text = f'{{"error": "{str(exc)}"}}'
            print(f"LLM call failed for procurement {pid}: {exc}", file=sys.stderr)

        parsed_json = None
        parse_status = "RAW_RECEIVED_PARSE_FAILED"
        val_status = "PARSED_SCHEMA_INVALID"

        if raw_text and run_status == "SUCCESS":
            try:
                clean_text = raw_text.strip()
                if clean_text.startswith("```"):
                    clean_text = clean_text.split("```")[1]
                    if clean_text.startswith("json"):
                        clean_text = clean_text[4:]
                    clean_text = clean_text.strip()
                parsed_json = json.loads(clean_text)
                parse_status = "PARSED_OK"
                if validate_shadow_output(parsed_json, manifest_json, active_cats):
                    val_status = "VALIDATED_SUCCESS"
            except Exception:
                pass

        if run_status != "SUCCESS":
            val_status = "API_FAILED"
            parse_status = "API_FAILED"

        run_status = val_status if val_status != "VALIDATED_SUCCESS" else "COMPLETED"
        if parse_status == "RAW_RECEIVED_PARSE_FAILED":
            run_status = "RAW_RECEIVED_PARSE_FAILED"

        # 6. Save model run and shadow prediction if success
        try:
            with crm_conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO crm_v3_model_inference_runs (
                        procurement_id, run_kind, model_name, model_version, prompt_version,
                        schema_version, raw_model_text, parse_status, validation_status, run_status, created_at
                    ) VALUES (%s, 'SHADOW', %s, %s, %s, 'v3_learning', %s, %s, %s, %s, NOW())
                    RETURNING id
                """, (pid, BASE_MODEL, BASE_MODEL, PROMPT_VERSION, raw_text, parse_status, val_status, run_status))
                run_id = cur.fetchone()[0]

                if val_status == "VALIDATED_SUCCESS" and parsed_json:
                    prob = float(parsed_json.get("has_target_probability", 0.5))
                    decision = str(parsed_json.get("has_target_decision", "UNCERTAIN")).upper()
                    prio = str(parsed_json.get("priority_candidate", "UNSCORED")).upper()
                    pred_cats = parsed_json.get("predicted_categories", [])
                    doc_rank = parsed_json.get("document_ranking", [])
                    conf = float(parsed_json.get("overall_confidence", prob))

                    cur.execute("""
                        INSERT INTO crm_v3_shadow_predictions (
                            snapshot_id, model_run_id, procurement_id, research_generation_hash,
                            has_target_probability, has_target_decision, priority_candidate,
                            predicted_categories_json, document_ranking_json, overall_confidence,
                            producer_version, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (
                        snap["snapshot_id"], run_id, pid, effective_gen_hash,
                        prob, decision, prio, json.dumps(pred_cats), json.dumps(doc_rank), conf, PRODUCER_VERSION
                    ))
                    print(f"Shadow prediction created for procurement {pid} (decision={decision}, prob={prob})")
                else:
                    print(f"Shadow model output invalid for procurement {pid} (val_status={val_status}, run_status={run_status}). Prediction omitted.")
            crm_conn.commit()
        except Exception as exc:
            print(f"Failed to write results to CRM DB: {exc}", file=sys.stderr)
            crm_conn.rollback()
            crm_conn.close()
            return False

        crm_conn.close()

        # 7. Release or retry queue row
        if val_status == "VALIDATED_SUCCESS":
            release_pre_research_queue(
                queue_id=queue_id,
                procurement_id=pid,
                pipeline_generation=pipeline_generation,
                research_generation_hash=gen_hash,
                outcome="SUCCESS",
                category_context=cat_ctx
            )
        else:
            if attempts + 1 >= 3:
                print(f"Attempts reached limit ({attempts + 1}) after failed run for procurement {pid}. Releasing as FAILED.")
                release_pre_research_queue(
                    queue_id=queue_id,
                    procurement_id=pid,
                    pipeline_generation=pipeline_generation,
                    research_generation_hash=gen_hash,
                    outcome="FAILED",
                    category_context=cat_ctx
                )
            else:
                print(f"Run failed for procurement {pid} but retry is allowed (attempt {attempts + 1}/3). Keeping in PRE_RESEARCH_WAITING.")

        return True

if __name__ == "__main__":
    predictor = ShadowPredictor()
    print("Starting CRM V3 Shadow Predictor loop (v3_real_truth)...")
    while True:
        try:
            did_work = predictor.run_cycle()
            time.sleep(2 if did_work else 5)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Predictor error: {e}", file=sys.stderr)
            time.sleep(5)
