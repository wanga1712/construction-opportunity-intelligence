"""CRM V3 Shadow Predictor Daemon (v3_real_truth)

Responsibilities:
- Select unpredicted blind pre-research snapshot
- Run Qwen2.5:7b with v3_pre_research_shadow_v1 prompt schema
- Include BOTH source_snapshot_json AND document_manifest_json in prompt (no parsed text/evidence)
- Respect shared GPU lock (acquire_gpu_inference) and yield to Hunter/Auditor foreground tasks
- Perform STRICT schema validation of model response (JSON keys, active categories, manifest keys, rank uniqueness)
- Record parse/validation status truthfully in crm_v3_model_inference_runs
- DO NOT insert shadow prediction on invalid model output (NO fabricated fallbacks)
- Producer version: v3_real_truth
"""

import os
import sys
import json
import time
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
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
BASE_MODEL = "qwen2.5:7b"
PROMPT_VERSION = "v3_pre_research_shadow_v1"

VALID_DECISIONS = {"YES", "NO", "UNCERTAIN"}
VALID_PRIORITIES = {"GOLD_CANDIDATE", "SILVER_CANDIDATE", "BRONZE_CANDIDATE", "LOW_PRIORITY", "UNSCORED"}

def get_crm_db():
    user = os.environ.get("CRM_DB_USER", "crm_app")
    password = os.environ.get("CRM_DB_PASSWORD")
    if not password:
        raise RuntimeError("Missing required environment variable CRM_DB_PASSWORD")
    host = os.environ.get("CRM_DB_HOST", "127.0.0.1")
    port = os.environ.get("CRM_DB_PORT", "5432")
    return psycopg2.connect(dbname="crm", user=user, password=password, host=host, port=port)

def fetch_active_categories(crm_conn) -> Set[str]:
    try:
        with crm_conn.cursor() as cur:
            cur.execute("SELECT code FROM crm_v3_canonical_categories WHERE is_active = True")
            return {r[0] for r in cur.fetchall()}
    except Exception:
        return set()

def validate_shadow_output(parsed: Any, manifest: List[Dict[str, Any]], active_cats: Set[str]) -> bool:
    if not isinstance(parsed, dict):
        return False

    # Check top-level required fields
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

    # Validate predicted_categories
    cats = parsed.get("predicted_categories")
    if not isinstance(cats, list):
        return False

    for c in cats:
        if not isinstance(c, dict) or "category_code" not in c or "confidence" not in c:
            return False
        code = str(c["category_code"])
        if active_cats and code not in active_cats:
            return False
        try:
            c_conf = float(c["confidence"])
            if not (0.0 <= c_conf <= 1.0):
                return False
        except (ValueError, TypeError):
            return False

    # Validate document_ranking against exact snapshot manifest keys
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

class ShadowPredictor:
    def __init__(self):
        pass

    def run_cycle(self) -> bool:
        if should_defer_document():
            # Yield GPU inference slot when Hunter/Auditor foreground tasks are active
            time.sleep(2)
            return False

        crm_conn = get_crm_db()
        try:
            active_cats = fetch_active_categories(crm_conn)

            with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT s.id as snapshot_id, s.procurement_id, s.research_generation_hash,
                           s.source_snapshot_json, s.document_manifest_json
                    FROM crm_v3_pre_research_snapshots s
                    LEFT JOIN crm_v3_shadow_predictions p ON s.id = p.snapshot_id
                    WHERE p.id IS NULL AND s.producer_version = %s
                    ORDER BY s.id ASC LIMIT 1
                """, (PRODUCER_VERSION,))
                snap = cur.fetchone()

                if not snap:
                    return False

                pid = snap["procurement_id"]
                gen_hash = snap["research_generation_hash"]
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
                    f"PROCUREMENT SOURCE METADATA:\n{json.dumps(source_json, ensure_ascii=False, indent=2)}\n\n"
                    f"DOCUMENT MANIFEST:\n{json.dumps(manifest_json, ensure_ascii=False, indent=2)}"
                )

                full_prompt = f"{system_prompt}\n\n{user_prompt}"

                # Acquire exclusive GPU lock for heavy Ollama inference
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
                except Exception as e:
                    raw_text = f'{{"error": "{str(e)}"}}'

                parsed_json = None
                parse_status = "RAW_RECEIVED_PARSE_FAILED"
                val_status = "PARSED_SCHEMA_INVALID"

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

                cur.execute("""
                    INSERT INTO crm_v3_model_inference_runs (
                        procurement_id, run_kind, model_name, model_version, prompt_version,
                        schema_version, raw_model_text, parse_status, validation_status, run_status, created_at
                    ) VALUES (%s, 'SHADOW', %s, %s, %s, 'v3_learning', %s, %s, %s, 'COMPLETED', NOW())
                    RETURNING id
                """, (pid, BASE_MODEL, BASE_MODEL, PROMPT_VERSION, raw_text, parse_status, val_status))
                run_id = cur.fetchone()["id"]

                # Insert into crm_v3_shadow_predictions ONLY IF validation succeeded!
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
                        snap["snapshot_id"], run_id, pid, gen_hash,
                        prob, decision, prio, json.dumps(pred_cats), json.dumps(doc_rank), conf, PRODUCER_VERSION
                    ))
                    print(f"Shadow prediction created for procurement {pid} (decision={decision}, prob={prob})")
                else:
                    print(f"Shadow model output invalid for procurement {pid} (val_status={val_status}). Prediction omitted.")

            crm_conn.commit()
            return True
        finally:
            crm_conn.close()

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
