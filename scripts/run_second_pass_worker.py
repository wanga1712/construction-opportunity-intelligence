"""Continuous Second Pass Worker for Production AI Assessment on Server 13.

Monitors completed document processing tasks and runs Second Pass LLM evaluation
using Qwen 2.5:7b with canonical taxonomy and strict semantic guardrails.

Concurrency: strictly sequential (QWEN_WORKERS=1).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path. Resolved from this file's own location:
# never from the shell's working directory, never from a parent directory and
# never from a sibling project.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Canonical configuration authority - the exact same bootstrap Streamlit and the
# CRM services use. Importing it loads <repo>/.env and nothing else.
import src.bootstrap  # noqa: E402,F401

import psycopg2
from psycopg2.extras import RealDictCursor

from src.services.ai_client import generate_with_meta
from src.bootstrap import crm_env_file
from src.services.crm_db_runtime import CrmDbConfigError, require_crm_db_connect_kwargs
from src.services.db_host_guard import LEGACY_DB_HOSTS, guard_connect_kwargs
from src.services.doc_db_runtime import DocDbConfigError, require_doc_db_connect_kwargs
from src.services.second_pass_service import (
    SECOND_PASS_MODEL,
    SECOND_PASS_PROMPT_VERSION,
    build_second_pass_prompt,
    compute_hash,
    extract_evidence_snippets,
    parse_second_pass_json,
    persist_second_pass,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SecondPassWorker] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SecondPassWorker")


class SecondPassDbIdentityMissing(RuntimeError):
    """The documented Second Pass DB identity is absent. Never fall back."""



_RUNNING = True


def _handle_signal(signum, frame):
    global _RUNNING
    logger.info(f"Received termination signal ({signum}). Gracefully stopping worker...")
    _RUNNING = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def _require_crm_connect_kwargs() -> Dict[str, Any]:
    """Canonical CRM connection kwargs. Fail fast; no role/host fallback."""
    try:
        kwargs = require_crm_db_connect_kwargs()
    except CrmDbConfigError as exc:
        raise SecondPassDbIdentityMissing(
            f"SECOND_PASS_DB_IDENTITY_MISSING: {exc}"
        ) from exc
    return guard_connect_kwargs(kwargs, "SECOND_PASS CRM_DB_HOST")


def _require_di_connect_kwargs() -> Dict[str, Any]:
    """Canonical document_intelligence kwargs (role doc_worker). No fallback."""
    try:
        kwargs = require_doc_db_connect_kwargs()
    except DocDbConfigError as exc:
        raise SecondPassDbIdentityMissing(
            f"SECOND_PASS_DB_IDENTITY_MISSING: {exc}"
        ) from exc
    return guard_connect_kwargs(kwargs, "SECOND_PASS S13_DOCUMENT_DB_HOST")


def get_crm_connection():
    """Connect to the canonical CRM DB using the documented runtime role."""
    return psycopg2.connect(**_require_crm_connect_kwargs())


def get_di_connection():
    """Connect to the canonical document_intelligence DB (role doc_worker)."""
    return psycopg2.connect(**_require_di_connect_kwargs())


def check_connection_only() -> int:
    """Read-only connectivity self-check. Never processes the backlog.

    Prints the effective configuration plus a single
    ``SELECT current_user, current_database()`` per canonical database.
    """
    crm_kwargs = _require_crm_connect_kwargs()
    di_kwargs = _require_di_connect_kwargs()

    legacy_refs = sum(
        1 for value in os.environ.values() if str(value).strip() in LEGACY_DB_HOSTS
    )

    print(f"CONFIG_SOURCE={crm_env_file()}")
    print(f"SECOND_PASS_DB_HOST={crm_kwargs['host']}")
    print(f"SECOND_PASS_DB_PORT={crm_kwargs['port']}")
    print(f"SECOND_PASS_DB_DATABASE={crm_kwargs['dbname']}")
    print(f"SECOND_PASS_DB_USER={crm_kwargs['user']}")
    print(f"SECOND_PASS_DOC_DB_HOST={di_kwargs['host']}")
    print(f"SECOND_PASS_DOC_DB_PORT={di_kwargs['port']}")
    print(f"SECOND_PASS_DOC_DB_DATABASE={di_kwargs['dbname']}")
    print(f"SECOND_PASS_DOC_DB_USER={di_kwargs['user']}")
    # src.bootstrap loads exactly one file: this project's own .env. There is no
    # cwd / ancestor / sibling discovery, so no foreign .env can be adopted.
    print("FOREIGN_ENV_LOADED=NO")
    print(f"LEGACY_HOST_REFERENCES_RUNTIME={legacy_refs}")
    print("POSTGRES_FALLBACK=NO")

    for label, kwargs in (("CRM", crm_kwargs), ("DOCUMENT", di_kwargs)):
        conn = psycopg2.connect(connect_timeout=8, **kwargs)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user, current_database()")
                user, database = cur.fetchone()
            print(f"{label}: current_user={user} current_database={database}")
        finally:
            conn.close()
    return 0




def fetch_candidate_procurements(crm_conn, di_conn, limit: int = 10) -> List[Dict[str, Any]]:
    """Find active actionable procurements with completed documents ready for Second Pass."""
    with di_conn.cursor(cursor_factory=RealDictCursor) as cur_di:
        # Find procurement IDs with completed document processing and evidence in DI
        cur_di.execute("""
            SELECT DISTINCT procurement_id
            FROM document_match_details
            ORDER BY procurement_id DESC
            LIMIT 500
        """)
        di_pids = [r["procurement_id"] for r in cur_di.fetchall()]

    if not di_pids:
        return []

    with crm_conn.cursor(cursor_factory=RealDictCursor) as cur_crm:
        # Filter active actionable procurements that do NOT have current Second Pass assessment
        cur_crm.execute("""
            SELECT 
                p.id, p.contract_number, p.auction_name, p.customer, p.initial_price,
                p.okpd_code, p.source_table, p.crm_stage, p.award_status, p.end_date,
                p.file_count, p.evidence_count, p.match_score, p.signal_score
            FROM crm_procurements p
            WHERE p.id = ANY(%s)
              AND p.crm_stage = 'torgi'
              AND p.award_status = 'submission_open'
              AND (p.end_date IS NULL OR p.end_date >= CURRENT_DATE)
              AND p.id NOT IN (
                  SELECT procurement_id
                  FROM procurement_ai_assessments
                  WHERE is_current = TRUE
                    AND prompt_version = %s
              )
            ORDER BY 
                COALESCE(p.signal_score, p.match_score, 0) DESC,
                p.end_date ASC NULLS LAST,
                p.initial_price DESC NULLS LAST,
                p.id DESC
            LIMIT %s
        """, (di_pids, SECOND_PASS_PROMPT_VERSION, limit))
        return [dict(r) for r in cur_crm.fetchall()]


def process_single_procurement(crm_conn, di_conn, proc: Dict[str, Any]) -> bool:
    """Execute Second Pass LLM evaluation for a single procurement."""
    pid = proc["id"]
    contract_num = proc.get("contract_number") or str(pid)
    fz = "223-FZ" if "223" in str(proc.get("source_table") or "") else "44-FZ"

    proc_meta = {
        "id": pid,
        "contract_number": contract_num,
        "auction_name": proc.get("auction_name") or "Закупка",
        "customer": proc.get("customer") or "Заказчик",
        "initial_price": float(proc.get("initial_price") or 0),
        "okpd_code": proc.get("okpd_code") or "",
        "fz": fz,
    }

    # 1. Extract evidence snippets
    snippets, doc_stats = extract_evidence_snippets(di_conn, pid)
    if not snippets:
        logger.warning(f"Procurement {pid} ({contract_num}): 0 evidence snippets found. Skipping.")
        return False

    # 2. Build prompt
    prompt = build_second_pass_prompt(proc_meta, doc_stats, snippets)
    prompt_hash = compute_hash(prompt)

    # 3. Check if identical prompt hash already evaluated (fingerprint check)
    with crm_conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM crm_v3_model_inference_runs
            WHERE procurement_id = %s AND prompt_hash = %s AND run_status = 'COMPLETED'
            LIMIT 1
        """, (pid, prompt_hash))
        existing_run = cur.fetchone()
        if existing_run:
            logger.info(f"Procurement {pid} ({contract_num}): identical prompt hash already evaluated in run {existing_run[0]}. Skipping duplicate.")
            return True

    logger.info(f"Evaluating procurement {pid} ({contract_num}, {fz}, price={proc_meta['initial_price']:,.0f} руб) with {len(snippets)} evidence snippets...")

    # 4. Sequential inference with Qwen 2.5:7b
    t0 = time.time()
    try:
        raw_text, meta = generate_with_meta(
            prompt,
            model=SECOND_PASS_MODEL,
            format_json=True,
            timeout=240,
            num_predict=768,
        )
    except Exception as exc:
        logger.error(f"Procurement {pid}: Qwen inference failed: {exc}")
        return False

    elapsed = time.time() - t0

    # 5. Parse JSON with canonical taxonomy and strict semantic guardrails
    evidence_corpus = "\n".join(s["text"] for s in snippets)
    parsed = parse_second_pass_json(raw_text, evidence_corpus=evidence_corpus)

    medal = parsed.get("model_medal", "WOOD")
    score = parsed.get("model_score", 0)
    facts_count = len(parsed.get("found_facts", []))
    cats_count = len(parsed.get("category_evaluations", []))

    # 6. Persist to DB
    run_id = persist_second_pass(crm_conn, pid, prompt, raw_text, parsed, meta)
    crm_conn.commit()

    logger.info(
        f"✓ Procurement {pid} COMPLETED: MODEL_MEDAL={medal} (score {score}), "
        f"{cats_count} cats, {facts_count} facts, run_id={run_id}, latency={elapsed:.1f}s"
    )
    return True


def run_worker_loop(interval: int = 15, limit_per_tick: int = 5, max_iterations: Optional[int] = None):
    """Main continuous processing loop."""
    logger.info(f"Starting Second Pass Production Worker: model={SECOND_PASS_MODEL}, prompt={SECOND_PASS_PROMPT_VERSION}, interval={interval}s")
    
    crm_conn = get_crm_connection()
    di_conn = get_di_connection()

    iterations = 0
    total_processed = 0

    try:
        while _RUNNING:
            iterations += 1
            try:
                candidates = fetch_candidate_procurements(crm_conn, di_conn, limit=limit_per_tick)
                if candidates:
                    logger.info(f"Found {len(candidates)} candidate procurements for Second Pass evaluation.")
                    for p in candidates:
                        if not _RUNNING:
                            break
                        success = process_single_procurement(crm_conn, di_conn, p)
                        if success:
                            total_processed += 1
                else:
                    logger.debug("No pending procurements for Second Pass. Waiting...")

            except Exception as loop_err:
                logger.error(f"Error in worker iteration: {loop_err}", exc_info=True)
                # Re-establish connections if broken
                try:
                    crm_conn.close()
                    di_conn.close()
                except Exception:
                    pass
                time.sleep(5)
                crm_conn = get_crm_connection()
                di_conn = get_di_connection()

            if max_iterations and iterations >= max_iterations:
                logger.info(f"Reached max iterations ({max_iterations}). Exiting.")
                break

            if _RUNNING:
                time.sleep(interval)

    finally:
        try:
            crm_conn.close()
            di_conn.close()
        except Exception:
            pass
        logger.info(f"Second Pass Worker stopped. Total processed in session: {total_processed}")


def main():
    parser = argparse.ArgumentParser(description="Run continuous Second Pass AI worker")
    parser.add_argument("--interval", type=int, default=15, help="Sleep interval between polling cycles (seconds)")
    parser.add_argument("--batch-size", type=int, default=5, help="Max candidates to claim per tick")
    parser.add_argument("--once", action="store_true", help="Run a single batch and exit")
    parser.add_argument("--limit", type=int, default=None, help="Total number of items to process before exiting")
    parser.add_argument(
        "--check-connection",
        action="store_true",
        help="Only verify canonical DB connectivity and exit; never processes backlog.",
    )
    args = parser.parse_args()

    if args.check_connection:
        raise SystemExit(check_connection_only())

    if args.once:
        run_worker_loop(interval=0, limit_per_tick=args.limit or 20, max_iterations=1)
    else:
        run_worker_loop(interval=args.interval, limit_per_tick=args.batch_size)


if __name__ == "__main__":
    main()
