import os
import sys
import logging
import json
import hashlib
import time
from typing import Any, Dict, List

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("corrective_canary")

# Add parent path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.autonomous_learning_loop import HunterAuditorOrchestrator
from src.services.commercial_routing_v3.autonomous_worker import AutonomousWorker
from src.services.commercial_routing_v3.autonomous_learning_loop import compute_md5

class CRMDBWrapper:
    def __init__(self, db_mgr):
        self.db = db_mgr

    def execute_query(self, query, params=None):
        return self.db.execute_query(query, params)

    def execute_scalar(self, query, params=None):
        rows = self.db.execute_query(query, params)
        if rows:
            val = rows[0][0] if isinstance(rows[0], (tuple, list)) else next(iter(rows[0].values()))
            return val
        return None

    def execute_update(self, query, params=None):
        return self.db.execute_update(query, params)

    def execute_query_one(self, query, params=None):
        rows = self.db.execute_query(query, params)
        return rows[0] if rows else None

def main():
    _, _, crm_db_orig, _ = connect_databases()
    crm_db = CRMDBWrapper(crm_db_orig)
    orchestrator = HunterAuditorOrchestrator(crm_db)
    worker = AutonomousWorker(orchestrator, crm_db)

    # 1. Clean up test ranges (999900 to 999999)
    logger.info("Cleaning up existing test data...")
    crm_db.execute_update(
        "DELETE FROM crm_v3_autonomous_analysis_traces WHERE procurement_id BETWEEN 999900 AND 999999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_v3_product_findings WHERE procurement_id BETWEEN 999900 AND 999999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_procurements WHERE id BETWEEN 999900 AND 999999"
    )
    
    doc_conn = orchestrator._get_doc_conn()
    try:
        with doc_conn.cursor() as cur:
            cur.execute("DELETE FROM document_processing_queue WHERE procurement_id BETWEEN 999900 AND 999999")
            cur.execute("DELETE FROM document_files WHERE procurement_id BETWEEN 999900 AND 999999")
            cur.execute("DELETE FROM document_matches WHERE procurement_id BETWEEN 999900 AND 999999")
            cur.execute("DELETE FROM document_match_details WHERE procurement_id BETWEEN 999900 AND 999999")
    finally:
        doc_conn.close()

    # Create active categories registry
    registry = orchestrator.load_active_categories()
    reg_hash = orchestrator.compute_registry_hash(registry)
    model_version = "qwen2.5:7b"
    from src.services.commercial_routing_v3.autonomous_learning_loop import (
        HUNTER_PROMPT_VERSION,
        AUDITOR_PROMPT_VERSION,
    )

    # =========================================================================
    # SCENARIO A: Backlog Starvation Prevention (Task 3)
    # =========================================================================
    logger.info("Setting up Scenario A: Backlog Starvation...")
    # Insert 150 mock procurements
    # Insert 150 corresponding queue items
    # Insert traces for the latest 100 queue items, leaving the oldest 50 unprocessed
    # Assert that run_once() picks up and processes one of the oldest 50 tasks!
    
    # We will use IDs: 999901 to 999900 + 150 = 1050
    # Let's insert procurements:
    for offset in range(1, 151):
        pid = 999900 + offset
        crm_db.execute_update(
            """
            INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (pid, f"CN-{pid}", f"Mock Procurement {pid}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz")
        )
    
    # Insert 150 queue rows in document DB
    doc_conn = orchestrator._get_doc_conn()
    try:
        with doc_conn.cursor() as cur:
            for offset in range(1, 151):
                pid = 999900 + offset
                # Insert queue row in order (increasing ID so latest has highest ID)
                cur.execute(
                    """
                    INSERT INTO document_processing_queue (procurement_id, status, pipeline_generation, is_locked)
                    VALUES (%s, 'NO_LINKS', 'S13_V2', FALSE)
                    """,
                    (pid,)
                )
    finally:
        doc_conn.close()

    # Now, write traces for the latest 100 procurements (pids 999951 to 9999150)
    # These traces must match the versioned identity hashes
    for offset in range(51, 151):
        pid = 999900 + offset
        facts = orchestrator.fetch_procurement_facts(pid)
        source_snapshot_hash = compute_md5(facts)
        
        # Zero files -> doc_set_hash and evidence_hash computation:
        docs, doc_set_hash = orchestrator.fetch_document_research_summary(pid)
        evidence = orchestrator.fetch_document_evidence(pid)
        evidence_hash = compute_md5(evidence)
        
        crm_db.execute_update(
            """
            INSERT INTO crm_v3_autonomous_analysis_traces (
                procurement_id, source_snapshot_hash, document_set_hash,
                extracted_evidence_hash, consensus_state, research_completeness,
                registry_hash, hunter_prompt_version, auditor_prompt_version,
                model_version, attempt_count
            ) VALUES (%s, %s, %s, %s, 'NO_DOCUMENTS', 'NO_DOCUMENTS', %s, %s, %s, %s, 1)
            """,
            (pid, source_snapshot_hash, doc_set_hash, evidence_hash, reg_hash, HUNTER_PROMPT_VERSION, AUDITOR_PROMPT_VERSION, model_version)
        )

    logger.info("Scenario A database initialized. Polling worker to process...")
    # The worker should skip pids 999951..9999150 (because they already have traces)
    # and pick pid 999950 (which is the newest of the unprocessed first 50!).
    # Let's run run_once()!
    processed_count = worker.run_once()
    assert processed_count == 1, "Expected worker to process exactly one task!"
    
    # Check that the trace for pid 999950 now exists in crm_db!
    trace_999950 = crm_db.execute_query_one(
        "SELECT id, consensus_state FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 999950"
    )
    assert trace_999950 is not None, "Expected trace to be written for procurement 999950!"
    assert trace_999950["consensus_state"] == "NO_DOCUMENTS", f"Expected consensus state NO_DOCUMENTS, got {trace_999950['consensus_state']}"
    logger.info("Scenario A: Starvation Prevention assert PASSED!")

    # =========================================================================
    # SCENARIO B: Idempotency Skip (Task 2)
    # =========================================================================
    logger.info("Setting up Scenario B: Idempotency Control...")
    # Since pid 999950 was just processed and has a valid trace, running worker again
    # should NOT process it, and since all newer/older have traces/are processed,
    # it should eventually return 0 if we mark all as processed.
    # To isolate, let's clean up all queue rows except pid 999950
    doc_conn = orchestrator._get_doc_conn()
    try:
        with doc_conn.cursor() as cur:
            cur.execute("DELETE FROM document_processing_queue WHERE procurement_id BETWEEN 999900 AND 999999 AND procurement_id != 999950")
    finally:
        doc_conn.close()

    # Now, there's only one task (999950) in the queue, and it already has a trace.
    # So calling run_once should return 0 (skipped idempotently!).
    processed_count = worker.run_once()
    assert processed_count == 0, f"Expected 0 tasks to be processed, but worker processed {processed_count}!"
    logger.info("Scenario B: Idempotency Skip assert PASSED!")

    # =========================================================================
    # SCENARIO C: Document-Set Change Rerun Trigger (Task 2)
    # =========================================================================
    logger.info("Setting up Scenario C: Document-Set Change Rerun...")
    # Let's create a new test procurement: pid = 999960
    pid = 999960
    crm_db.execute_update(
        """
        INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (pid, f"CN-{pid}", f"Mock Procurement {pid}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz")
    )
    
    # Insert queue row as COMPLETED
    doc_conn = orchestrator._get_doc_conn()
    try:
        with doc_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO document_processing_queue (procurement_id, status, pipeline_generation, is_locked)
                VALUES (%s, 'COMPLETED', 'S13_V2', FALSE)
                """,
                (pid,)
            )
            # Insert a document file
            cur.execute(
                """
                INSERT INTO document_files (id, procurement_id, file_name, download_status)
                VALUES (999961, %s, 'doc1.pdf', 'COMPLETED')
                """,
                (pid,)
            )
            cur.execute(
                """
                INSERT INTO document_processing_results (file_id, status, pages_processed, rows_extracted)
                VALUES (999961, 'COMPLETED', 1, 100)
                """,
            )
    finally:
        doc_conn.close()

    # Now run worker. This should process the task and write a trace because no trace exists yet.
    # Note: since we don't have real document content, we temporarily mock the LLM calls in orchestrator
    # to return a static mock response to avoid needing GPU runtime/calling local Ollama!
    import src.services.commercial_routing_v3.autonomous_learning_loop as loop_module
    
    # Save original method
    orig_generate = loop_module.generate_v3_routing_with_bounded_retry
    
    # Create a mock
    mock_hunter = {
        "object_sector": "Mock Sector",
        "object_type": "Mock Type",
        "object_subtype": "Mock Subtype",
        "procurement_mode": "PROJECT",
        "category_scope": "IN_CATEGORY",
        "categories": ["43.21.10"],
        "subcategories": [],
        "detected_products": [
            {
                "category_code": "43.21.10",
                "product_type": "Mock Product",
                "product_name_normalized": "Mock Cable",
                "brand": None,
                "model": None,
                "quantity": 10.0,
                "unit": "meters",
                "raw_description": "Mock Cable Description",
                "evidence_text": "Mock Evidence Text",
                "document_name": "doc1.pdf",
                "locator": {"page": "1", "sheet": None, "row": None, "position_number": None}
            }
        ],
        "commercial_entry": "COMMERCIAL",
        "medal_hypothesis": "GOLD",
        "confidence": 0.9,
        "evidence_references": [],
        "missing_information": []
    }
    
    mock_auditor = {
        "object": {"verdict": "AGREE", "why": "looks good", "evidence": ""},
        "procurement_mode": {"verdict": "AGREE", "why": "looks good", "evidence": ""},
        "category_scope": {"verdict": "AGREE", "why": "looks good", "evidence": ""},
        "categories": [{"category_code": "43.21.10", "verdict": "AGREE", "why": "", "evidence": ""}],
        "products": [{"product_name_normalized": "Mock Cable", "verdict": "AGREE", "why": "", "evidence": ""}],
        "commercial_entry": {"verdict": "AGREE", "why": "looks good", "evidence": ""},
        "medal": {"verdict": "AGREE", "why": "looks good", "evidence": ""},
        "auditor_discovered_candidate": []
    }
    
    call_count = 0
    def mock_routing_func(prompt, procurement_id, prompt_version):
        nonlocal call_count
        call_count += 1
        if "HUNTER" in prompt or "high recall" in prompt.lower() or "high_recall" in prompt.lower() or "hunter" in prompt.lower():
            return mock_hunter, {"raw_text": json.dumps(mock_hunter)}, 0
        else:
            return mock_auditor, {"raw_text": json.dumps(mock_auditor)}, 0
            
    loop_module.generate_v3_routing_with_bounded_retry = mock_routing_func

    try:
        # Run worker
        processed_count = worker.run_once()
        assert processed_count == 1, "Expected to process task 999960"
        
        # Verify trace was written
        trace_999960 = crm_db.execute_query_one(
            "SELECT id, attempt_count, document_set_hash FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 999960"
        )
        assert trace_999960 is not None, "Expected trace to exist for 999960"
        assert trace_999960["attempt_count"] == 1, f"Expected attempt 1, got {trace_999960['attempt_count']}"
        orig_doc_hash = trace_999960["document_set_hash"]
        
        # Now, modify the document set! Change download status of file 999961 to 'FAILED' or add a new file
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO document_files (id, procurement_id, file_name, download_status)
                    VALUES (999962, %s, 'doc2.pdf', 'COMPLETED')
                    """,
                    (pid,)
                )
                cur.execute(
                    """
                    INSERT INTO document_processing_results (file_id, status, pages_processed, rows_extracted)
                    VALUES (999962, 'COMPLETED', 2, 200)
                    """,
                )
        finally:
            doc_conn.close()
            
        # The document set hash has changed now!
        # Run worker again. It should detect document-set change and trigger a rerun!
        processed_count = worker.run_once()
        assert processed_count == 1, "Expected to rerun task 999960 because of document-set hash change!"
        
        # Verify new trace exists with attempt_count = 2 and a new document_set_hash!
        traces = crm_db.execute_query(
            "SELECT id, attempt_count, document_set_hash FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 999960 ORDER BY id DESC"
        )
        assert len(traces) == 2, f"Expected 2 traces for 999960, got {len(traces)}"
        assert traces[0]["attempt_count"] == 2, f"Expected latest trace to have attempt 2, got {traces[0]['attempt_count']}"
        assert traces[0]["document_set_hash"] != orig_doc_hash, "Expected document set hash to have changed!"
        logger.info("Scenario C: Document-Set Change Rerun assert PASSED!")

        # =========================================================================
        # SCENARIO D: Retry Limit (Task 4)
        # =========================================================================
        logger.info("Setting up Scenario D: Retry Limit...")
        # Clean up existing test queue rows
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                cur.execute("DELETE FROM document_processing_queue WHERE procurement_id = 999960")
        finally:
            doc_conn.close()
            
        # Let's create a task that always fails.
        def failing_routing_func(prompt, procurement_id, prompt_version):
            raise RuntimeError("Mock LLM Failure")
            
        loop_module.generate_v3_routing_with_bounded_retry = failing_routing_func
        
        # Create new test procurement: pid = 999970
        pid = 999970
        crm_db.execute_update(
            """
            INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (pid, f"CN-{pid}", f"Mock Procurement {pid}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz")
        )
        
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO document_processing_queue (procurement_id, status, pipeline_generation, is_locked)
                    VALUES (%s, 'COMPLETED', 'S13_V2', FALSE)
                    """,
                    (pid,)
                )
        finally:
            doc_conn.close()

        # Run 1: writes attempt 1
        processed = worker.run_once()
        assert processed == 1, "Expected worker to run and record failure trace (attempt 1)"
        
        # Run 2: writes attempt 2
        processed = worker.run_once()
        assert processed == 1, "Expected worker to run and record failure trace (attempt 2)"
        
        # Run 3: writes attempt 3
        processed = worker.run_once()
        assert processed == 1, "Expected worker to run and record failure trace (attempt 3)"
        
        # Verify 3 traces are written in CRM DB
        traces = crm_db.execute_query(
            "SELECT id, attempt_count, consensus_state FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 999970 ORDER BY id ASC"
        )
        assert len(traces) == 3, f"Expected exactly 3 traces, got {len(traces)}"
        assert traces[0]["attempt_count"] == 1
        assert traces[1]["attempt_count"] == 2
        assert traces[2]["attempt_count"] == 3
        assert all(t["consensus_state"] == "FAILED_PROCESSING" for t in traces)
        
        # Run 4: should skip because attempts >= 3!
        processed = worker.run_once()
        assert processed == 0, f"Expected task to be skipped since it hit retry limit, but run_once returned {processed}!"
        
        # Verify no 4th trace was written
        traces_after = crm_db.execute_query(
            "SELECT id FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 999970"
        )
        assert len(traces_after) == 3, f"Expected trace count to remain 3, got {len(traces_after)}"
        logger.info("Scenario D: Retry Limit and Single Owner failure trace asserts PASSED!")

        # =========================================================================
        # SCENARIO E: Queue Status Aggregation Logic (Task 5)
        # =========================================================================
        logger.info("Setting up Scenario E: Queue Status Aggregation...")
        # Clean up existing test queue rows
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                cur.execute("DELETE FROM document_processing_queue WHERE procurement_id = 999970")
        finally:
            doc_conn.close()
            
        # We restore mock_routing_func (which succeeds)
        loop_module.generate_v3_routing_with_bounded_retry = mock_routing_func
        
        # Create test procurement: pid = 999980
        pid = 999980
        crm_db.execute_update(
            """
            INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (pid, f"CN-{pid}", f"Mock Procurement {pid}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz")
        )
        
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                # Insert queue row (even if status in queue is FAILED in db, effective status will be COMPLETED because of files!)
                cur.execute(
                    """
                    INSERT INTO document_processing_queue (procurement_id, status, pipeline_generation, is_locked)
                    VALUES (%s, 'FAILED', 'S13_V2', FALSE)
                    """,
                    (pid,)
                )
                # File A: DOWNLOAD_FAILED
                cur.execute(
                    """
                    INSERT INTO document_files (id, procurement_id, file_name, download_status)
                    VALUES (999981, %s, 'failed_doc.pdf', 'FAILED')
                    """,
                    (pid,)
                )
                # File B: COMPLETED
                cur.execute(
                    """
                    INSERT INTO document_files (id, procurement_id, file_name, download_status)
                    VALUES (999982, %s, 'ok_doc.pdf', 'COMPLETED')
                    """,
                    (pid,)
                )
                cur.execute(
                    """
                    INSERT INTO document_processing_results (file_id, status, pages_processed, rows_extracted)
                    VALUES (999982, 'COMPLETED', 1, 100)
                    """,
                )
        finally:
            doc_conn.close()

        # Run worker: it should aggregate effective status = COMPLETED (since ok_doc.pdf parsed successfully)
        # and therefore run the LLM learning loop instead of writing terminal FAILED trace!
        processed = worker.run_once()
        assert processed == 1
        
        # Verify trace has research_completeness = 'PARTIAL' and consensus_state = 'AGREE' (succeeded)
        trace_999980 = crm_db.execute_query_one(
            "SELECT id, consensus_state, research_completeness FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 999980"
        )
        assert trace_999980 is not None
        assert trace_999980["research_completeness"] == "PARTIAL", f"Expected PARTIAL completeness due to failed_doc.pdf, got {trace_999980['research_completeness']}"
        assert trace_999980["consensus_state"] == "AGREE", f"Expected AGREE consensus from successful Hunter-Auditor run, got {trace_999980['consensus_state']}"
        logger.info("Scenario E: Queue Status Aggregation assert PASSED!")

    finally:
        # Restore original prompt routing function
        loop_module.generate_v3_routing_with_bounded_retry = orig_generate

    # Clean up test ranges at the end of success
    logger.info("Cleaning up test data at the end...")
    crm_db.execute_update(
        "DELETE FROM crm_v3_autonomous_analysis_traces WHERE procurement_id BETWEEN 999900 AND 999999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_v3_product_findings WHERE procurement_id BETWEEN 999900 AND 999999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_procurements WHERE id BETWEEN 999900 AND 999999"
    )
    
    doc_conn = orchestrator._get_doc_conn()
    try:
        with doc_conn.cursor() as cur:
            cur.execute("DELETE FROM document_processing_queue WHERE procurement_id BETWEEN 999900 AND 999999")
            cur.execute("DELETE FROM document_files WHERE procurement_id BETWEEN 999900 AND 999999")
            cur.execute("DELETE FROM document_matches WHERE procurement_id BETWEEN 999900 AND 999999")
            cur.execute("DELETE FROM document_match_details WHERE procurement_id BETWEEN 999900 AND 999999")
    finally:
        doc_conn.close()

    print("CORRECTIVE_CANARY_8=PASS")
    logger.info("All asserts passed successfully!")

if __name__ == "__main__":
    main()
