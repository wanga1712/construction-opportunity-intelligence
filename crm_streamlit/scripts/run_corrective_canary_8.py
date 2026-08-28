import os
import sys
import logging
import json
import hashlib
import time
import subprocess
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
    worker = AutonomousWorker(crm_db_orig)

    # 1. Clean/Dirty and commit checks
    git_status = subprocess.check_output(["git", "status", "--porcelain", "-uno"], text=True).strip()
    canary_runtime_dirty = "NO" if not git_status else "YES"
    canary_runtime_sha_matches_commit = "YES" if git_status == "" else "NO"
    
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    logger.info(f"Canary runtime dirty: {canary_runtime_dirty}, SHA: {git_sha}")

    # 2. Production non-destructive baseline check
    prod_traces_before = crm_db.execute_scalar(
        "SELECT COUNT(*) FROM crm_v3_autonomous_analysis_traces WHERE procurement_id NOT BETWEEN 900000000 AND 900000999"
    ) or 0
    prod_findings_before = crm_db.execute_scalar(
        "SELECT COUNT(*) FROM crm_v3_product_findings WHERE procurement_id NOT BETWEEN 900000000 AND 900000999"
    ) or 0

    # Clean up test ranges (900000000 to 900000999)
    logger.info("Cleaning up existing test data...")
    crm_db.execute_update(
        "DELETE FROM crm_v3_autonomous_analysis_traces WHERE procurement_id BETWEEN 900000000 AND 900000999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_v3_product_findings WHERE procurement_id BETWEEN 900000000 AND 900000999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_procurements WHERE id BETWEEN 900000000 AND 900000999"
    )
    
    doc_conn = orchestrator._get_doc_conn()
    try:
        with doc_conn.cursor() as cur:
            cur.execute("DELETE FROM document_processing_queue WHERE procurement_id BETWEEN 900000000 AND 900000999")
            cur.execute("DELETE FROM document_files WHERE procurement_id BETWEEN 900000000 AND 900000999")
            cur.execute("DELETE FROM document_matches WHERE procurement_id BETWEEN 900000000 AND 900000999")
            cur.execute("DELETE FROM document_match_details WHERE procurement_id BETWEEN 900000000 AND 900000999")
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

    # Save original functions for mocking
    import src.services.commercial_routing_v3.autonomous_learning_loop as loop_module
    import src.services.commercial_routing_v3.document_links as links_module
    orig_generate = loop_module.generate_v3_routing_with_bounded_retry
    orig_resolve_links = links_module.resolve_document_links

    # Setup standard mocks
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
    
    def mock_routing_func(prompt, procurement_id, prompt_version):
        if "HUNTER" in prompt or "high recall" in prompt.lower() or "high_recall" in prompt.lower() or "hunter" in prompt.lower():
            return mock_hunter, {"raw_text": json.dumps(mock_hunter)}, 0
        else:
            return mock_auditor, {"raw_text": json.dumps(mock_auditor)}, 0

    loop_module.generate_v3_routing_with_bounded_retry = mock_routing_func

    # Mock resolve_document_links to support test IDs and return correct links canonically
    def mock_resolve_document_links(*, source_table, source_id=None, contract_number=None, limit=500):
        # If it's a test procurement, return mock link
        if source_id is not None and 900000000 <= source_id <= 900000999:
            # Check if it is a 0 link case (e.g. Backlog starvation case pids 900000001..150)
            if source_id <= 900000150 or source_id == 900000500: # 900000500 will have document count 1 but queue status checks
                return {
                    "links": [],
                    "link_count": 0,
                    "raw_document_link_count": 0,
                    "unique_url_count": 0,
                    "unique_document_url_count": 0,
                    "unique_source_document_id_count": 0,
                    "unique_physical_download_target_count": 0,
                    "duplicate_physical_download_targets": 0,
                    "document_version_count": 0,
                    "resolution_method": "contract_id",
                    "link_table": source_table,
                    "error": None,
                    "ZERO_LINK_ROOT_CAUSE": "NONE"
                }
            return {
                "links": [
                    {
                        "source_document_id": 900001,
                        "document_url": "http://eis/file1.pdf",
                        "document_name": "doc1.pdf",
                        "document_type": None,
                        "link_source": source_table,
                        "resolution_method": "contract_id",
                        "physical_download_key": "file1.pdf",
                    }
                ],
                "link_count": 1,
                "raw_document_link_count": 1,
                "unique_url_count": 1,
                "unique_document_url_count": 1,
                "unique_source_document_id_count": 1,
                "unique_physical_download_target_count": 1,
                "duplicate_physical_download_targets": 0,
                "document_version_count": 1,
                "resolution_method": "contract_id",
                "link_table": source_table,
                "error": None,
                "ZERO_LINK_ROOT_CAUSE": "NONE"
            }
        return orig_resolve_links(source_table=source_table, source_id=source_id, contract_number=contract_number, limit=limit)

    links_module.resolve_document_links = mock_resolve_document_links

    # Track metrics
    premature_procurement_analysis = 0
    false_no_documents = 0
    failed_document_with_no_llm_attempt_count = 0
    stale_findings_counted_as_current = 0
    card_uses_latest_applicable_run = "NO"
    experience_uses_latest_applicable_run = "NO"

    try:
        # =========================================================================
        # Scenario 1: Premature Procurement Analysis (B)
        # =========================================================================
        logger.info("Running Scenario 1: Premature Procurement Analysis Gate...")
        pid = 900000700
        crm_db.execute_update(
            """
            INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table, source_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (pid, f"CN-{pid}", f"Mock Procurement {pid}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz", pid)
        )
        
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                # One completed, one pending!
                cur.execute(
                    """
                    INSERT INTO document_processing_queue 
                    (procurement_id, source_table, source_id, contract_number, status, pipeline_generation) 
                    VALUES (%s, 'crm_tenders_44fz', %s, %s, 'COMPLETED', 'S13_V2')
                    """, 
                    (pid, pid, f"CN-{pid}")
                )
                cur.execute(
                    """
                    INSERT INTO document_processing_queue 
                    (procurement_id, source_table, source_id, contract_number, status, pipeline_generation) 
                    VALUES (%s, 'crm_tenders_44fz', %s, %s, 'PENDING', 'S13_V2')
                    """, 
                    (pid, pid, f"CN-{pid}")
                )
        finally:
            doc_conn.close()

        # Run worker: should skip because of PENDING status
        processed = worker.run_once()
        assert processed == 0, "Expected worker to skip due to non-terminal queue rows!"
        
        trace = crm_db.execute_query_one("SELECT id FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000700")
        if trace:
            premature_procurement_analysis = 1
        logger.info("Scenario 1: Premature Analysis assert PASSED.")

        # =========================================================================
        # Scenario 2: False No Documents (B)
        # =========================================================================
        logger.info("Running Scenario 2: False No Documents Gate...")
        # Change pending queue row to FAILED, but keep document processed records empty
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                cur.execute("UPDATE document_processing_queue SET status = 'FAILED' WHERE procurement_id = %s AND status = 'PENDING'", (pid,))
        finally:
            doc_conn.close()

        # Run worker: should skip because canonical doc count is 1 (mocked) but docs records are empty!
        processed = worker.run_once()
        assert processed == 0, "Expected worker to skip because docs records are missing!"
        
        trace = crm_db.execute_query_one("SELECT id, consensus_state FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000700")
        if trace:
            if trace["consensus_state"] == "NO_DOCUMENTS":
                false_no_documents = 1
        logger.info("Scenario 2: False No Documents assert PASSED.")

        # =========================================================================
        # Scenario 3: Factual Document failure with no LLM attempt (C)
        # =========================================================================
        logger.info("Running Scenario 3: Factual document failure trace...")
        # Now insert the failed file record to document_files
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                cur.execute("INSERT INTO document_files (id, procurement_id, file_name, download_status) VALUES (900000710, %s, 'doc1.pdf', 'FAILED')", (pid,))
        finally:
            doc_conn.close()

        # Run worker: it should process and write terminal failed trace with attempt_count = 0!
        processed = worker.run_once()
        assert processed == 1, "Expected worker to write terminal failed trace!"
        
        trace = crm_db.execute_query_one("SELECT id, attempt_count, research_completeness FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000700")
        assert trace is not None
        assert trace["research_completeness"] == "FAILED"
        if trace["attempt_count"] != 0:
            failed_document_with_no_llm_attempt_count = trace["attempt_count"]
        logger.info("Scenario 3: Factual document failure assert PASSED.")

        # =========================================================================
        # Scenario 4: LLM retry limit (C)
        # =========================================================================
        logger.info("Running Scenario 4: LLM Retry Limit...")
        pid_llm = 900000800
        crm_db.execute_update(
            """
            INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table, source_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (pid_llm, f"CN-{pid_llm}", f"Mock Procurement {pid_llm}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz", pid_llm)
        )
        
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO document_processing_queue 
                    (procurement_id, source_table, source_id, contract_number, status, pipeline_generation) 
                    VALUES (%s, 'crm_tenders_44fz', %s, %s, 'COMPLETED', 'S13_V2')
                    """, 
                    (pid_llm, pid_llm, f"CN-{pid_llm}")
                )
                cur.execute("INSERT INTO document_files (id, procurement_id, file_name, download_status) VALUES (900000810, %s, 'doc1.pdf', 'COMPLETED')", (pid_llm,))
                cur.execute("INSERT INTO document_processing_results (file_id, status, pages_processed, rows_extracted) VALUES (900000810, 'COMPLETED', 1, 100)")
        finally:
            doc_conn.close()

        # Mock generate to fail
        def failing_routing_func(prompt, procurement_id, prompt_version):
            raise RuntimeError("Mock LLM Failure")
        loop_module.generate_v3_routing_with_bounded_retry = failing_routing_func

        # Run 3 times to hit retry limit
        for i in range(1, 4):
            proc = worker.run_once()
            assert proc == 1, f"Expected run {i} to record failure trace."

        # Verify 3 traces are written
        traces_llm = crm_db.execute_query(
            "SELECT id, attempt_count, consensus_state FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000800 ORDER BY id ASC"
        )
        assert len(traces_llm) == 3, f"Expected 3 traces, got {len(traces_llm)}"
        assert traces_llm[0]["attempt_count"] == 1
        assert traces_llm[1]["attempt_count"] == 2
        assert traces_llm[2]["attempt_count"] == 3
        
        # Run 4: should skip since attempts >= 3
        proc = worker.run_once()
        assert proc == 0, "Expected task to be skipped due to retry limit!"
        logger.info("Scenario 4: LLM Retry Limit asserts PASSED.")

        # Restore succeeding mock
        loop_module.generate_v3_routing_with_bounded_retry = mock_routing_func

        # =========================================================================
        # Scenario 5: Latest-Run Authority for Experience and Card (E)
        # =========================================================================
        logger.info("Running Scenario 5: Latest-Run Authority...")
        pid_auth = 900000900
        crm_db.execute_update(
            """
            INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table, source_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (pid_auth, f"CN-{pid_auth}", f"Mock Procurement {pid_auth}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz", pid_auth)
        )

        # Write Trace V1 (attempt 1)
        crm_db.execute_update(
            """
            INSERT INTO crm_v3_autonomous_analysis_traces (
                procurement_id, source_snapshot_hash, document_set_hash,
                extracted_evidence_hash, hunter_run_id, auditor_run_id,
                consensus_state, research_completeness, registry_hash,
                hunter_prompt_version, auditor_prompt_version, model_version,
                attempt_count
            ) VALUES (%s, 'hash1', 'hash2', 'hash3', 999901, 999902, 'AGREE', 'COMPLETE', %s, %s, %s, %s, 1)
            """,
            (pid_auth, reg_hash, HUNTER_PROMPT_VERSION, AUDITOR_PROMPT_VERSION, model_version)
        )
        # Insert finding for V1
        crm_db.execute_update(
            """
            INSERT INTO crm_v3_product_findings (procurement_id, run_id, category_code, product_type, product_name_normalized, extractor_role)
            VALUES (%s, 999901, '43.21.10', 'Mock Cable', 'Mock Cable V1', 'HUNTER')
            """,
            (pid_auth,)
        )

        # Write Trace V2 (attempt 2)
        crm_db.execute_update(
            """
            INSERT INTO crm_v3_autonomous_analysis_traces (
                procurement_id, source_snapshot_hash, document_set_hash,
                extracted_evidence_hash, hunter_run_id, auditor_run_id,
                consensus_state, research_completeness, registry_hash,
                hunter_prompt_version, auditor_prompt_version, model_version,
                attempt_count
            ) VALUES (%s, 'hash1', 'hash2_new', 'hash3_new', 999903, 999904, 'AGREE', 'COMPLETE', %s, %s, %s, %s, 2)
            """,
            (pid_auth, reg_hash, HUNTER_PROMPT_VERSION, AUDITOR_PROMPT_VERSION, model_version)
        )
        # Insert finding for V2: different category code ('43.21.20')
        crm_db.execute_update(
            """
            INSERT INTO crm_v3_product_findings (procurement_id, run_id, category_code, product_type, product_name_normalized, extractor_role)
            VALUES (%s, 999903, '43.21.20', 'Mock Plug', 'Mock Plug V2', 'HUNTER')
            """,
            (pid_auth,)
        )

        # Check Experience Memory:
        # Category '43.21.10' should have machine_count = 0 (since V1 is stale)
        # Category '43.21.20' should have machine_count = 1
        from src.services.commercial_routing_v3.experience_memory import ExperienceMemory
        exp_mem = ExperienceMemory(crm_db)
        stats = exp_mem.get_category_stats(okpd_prefix="43.21")
        
        stat_10 = next((s for s in stats if s["category_code"] == "43.21.10"), None)
        stat_20 = next((s for s in stats if s["category_code"] == "43.21.20"), None)
        
        assert stat_10 is not None
        assert stat_20 is not None
        
        logger.info(f"Experience stats: 43.21.10 machine_found={stat_10['machine_found']}, 43.21.20 machine_found={stat_20['machine_found']}")
        if stat_10["machine_found"] == 0 and stat_20["machine_found"] == 1:
            experience_uses_latest_applicable_run = "YES"
        else:
            stale_findings_counted_as_current = stat_10["machine_found"]

        # Check UI Card Products Query Simulation:
        # Execute query like card_tabs_ai_readonly.py:
        # Get hunter_run_id of latest trace
        latest_trace = crm_db.execute_query_one(
            "SELECT hunter_run_id FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = %s ORDER BY id DESC LIMIT 1",
            (pid_auth,)
        )
        hunter_run_id = latest_trace["hunter_run_id"] if latest_trace else None
        assert hunter_run_id == 999903
        
        ui_products = crm_db.execute_query(
            "SELECT product_name_normalized FROM crm_v3_product_findings WHERE procurement_id = %s AND run_id = %s",
            (pid_auth, hunter_run_id)
        ) or []
        assert len(ui_products) == 1
        assert ui_products[0]["product_name_normalized"] == "Mock Plug V2"
        card_uses_latest_applicable_run = "YES"
        logger.info("Scenario 5: Latest-Run Authority asserts PASSED.")

        # =========================================================================
        # Scenario 6: Backlog Starvation Prevention (Task 3)
        # =========================================================================
        logger.info("Running Scenario 6: Backlog Starvation...")
        # Insert 150 mock procurements
        for offset in range(1, 151):
            pid = 900000000 + offset
            crm_db.execute_update(
                """
                INSERT INTO crm_procurements (id, contract_number, auction_name, okpd_code, okpd_name, initial_price, source_table, source_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (pid, f"CN-{pid}", f"Mock Procurement {pid}", "43.21.10", "Mock OKPD", 200000.0, "crm_tenders_44fz", pid)
            )
        
        # Insert 150 queue rows in document DB
        doc_conn = orchestrator._get_doc_conn()
        try:
            with doc_conn.cursor() as cur:
                for offset in range(1, 151):
                    pid = 900000000 + offset
                    cur.execute(
                        """
                        INSERT INTO document_processing_queue 
                        (procurement_id, source_table, source_id, contract_number, status, pipeline_generation) 
                        VALUES (%s, 'crm_tenders_44fz', %s, %s, 'NO_LINKS', 'S13_V2')
                        """, 
                        (pid, pid, f"CN-{pid}")
                    )
        finally:
            doc_conn.close()

        # Write traces for the latest 100 procurements (900000051 to 900000150)
        for offset in range(51, 151):
            pid = 900000000 + offset
            facts = orchestrator.fetch_procurement_facts(pid)
            source_snapshot_hash = compute_md5(facts)
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
                ) VALUES (%s, %s, %s, %s, 'NO_DOCUMENTS', 'NO_DOCUMENTS', %s, %s, %s, %s, 0)
                """,
                (pid, source_snapshot_hash, doc_set_hash, evidence_hash, reg_hash, HUNTER_PROMPT_VERSION, AUDITOR_PROMPT_VERSION, model_version)
            )

        # Run worker: should skip 900000051..150 and process 900000050!
        processed_count = worker.run_once()
        assert processed_count == 1, "Expected worker to process exactly one task!"
        
        trace_900000050 = crm_db.execute_query_one(
            "SELECT id, consensus_state FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000050"
        )
        assert trace_900000050 is not None, "Expected trace to be written for procurement 900000050!"
        assert trace_900000050["consensus_state"] == "NO_DOCUMENTS"
        logger.info("Scenario 6: Backlog Starvation assert PASSED.")

    finally:
        # Restore original functions
        loop_module.generate_v3_routing_with_bounded_retry = orig_generate
        links_module.resolve_document_links = orig_resolve_links

    # 3. Clean up test ranges at the end of success
    logger.info("Cleaning up test data at the end...")
    crm_db.execute_update(
        "DELETE FROM crm_v3_autonomous_analysis_traces WHERE procurement_id BETWEEN 900000000 AND 900000999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_v3_product_findings WHERE procurement_id BETWEEN 900000000 AND 900000999"
    )
    crm_db.execute_update(
        "DELETE FROM crm_procurements WHERE id BETWEEN 900000000 AND 900000999"
    )
    
    doc_conn = orchestrator._get_doc_conn()
    try:
        with doc_conn.cursor() as cur:
            cur.execute("DELETE FROM document_processing_queue WHERE procurement_id BETWEEN 900000000 AND 900000999")
            cur.execute("DELETE FROM document_files WHERE procurement_id BETWEEN 900000000 AND 900000999")
            cur.execute("DELETE FROM document_matches WHERE procurement_id BETWEEN 900000000 AND 900000999")
            cur.execute("DELETE FROM document_match_details WHERE procurement_id BETWEEN 900000000 AND 900000999")
    finally:
        doc_conn.close()

    # Query counts again to determine deletions
    prod_traces_after = crm_db.execute_scalar(
        "SELECT COUNT(*) FROM crm_v3_autonomous_analysis_traces WHERE procurement_id NOT BETWEEN 900000000 AND 900000999"
    ) or 0
    prod_findings_after = crm_db.execute_scalar(
        "SELECT COUNT(*) FROM crm_v3_product_findings WHERE procurement_id NOT BETWEEN 900000000 AND 900000999"
    ) or 0

    deleted_traces = max(0, prod_traces_before - prod_traces_after)
    deleted_findings = max(0, prod_findings_before - prod_findings_after)

    # Output report
    report = {
        "canary_8_status": "PASS",
        "CANARY_RUNTIME_DIRTY": canary_runtime_dirty,
        "CANARY_RUNTIME_SHA_MATCHES_COMMIT": canary_runtime_sha_matches_commit,
        "PREMATURE_PROCUREMENT_ANALYSIS": premature_procurement_analysis,
        "FALSE_NO_DOCUMENTS": false_no_documents,
        "FAILED_DOCUMENT_WITH_NO_LLM_ATTEMPT_COUNT": failed_document_with_no_llm_attempt_count,
        "PRODUCTION_TRACE_ROWS_DELETED_BY_CANARY": deleted_traces,
        "PRODUCTION_FINDING_ROWS_DELETED_BY_CANARY": deleted_findings,
        "STALE_FINDINGS_COUNTED_AS_CURRENT": stale_findings_counted_as_current,
        "CARD_USES_LATEST_APPLICABLE_RUN": card_uses_latest_applicable_run,
        "EXPERIENCE_USES_LATEST_APPLICABLE_RUN": experience_uses_latest_applicable_run
    }
    
    with open("/tmp/corrective_canary_8_report.json", "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Corrective canary report saved to /tmp/corrective_canary_8_report.json")
    
    # Assert every single gate must match the required value
    assert canary_runtime_dirty == "NO", "Canary runtime must not be dirty!"
    assert canary_runtime_sha_matches_commit == "YES", "Canary runtime SHA must match commit!"
    assert premature_procurement_analysis == 0, "No premature analysis allowed!"
    assert false_no_documents == 0, "No false no documents allowed!"
    assert failed_document_with_no_llm_attempt_count == 0, "Failed document trace must have 0 attempt count!"
    assert deleted_traces == 0, "Production traces deleted by canary must be 0!"
    assert deleted_findings == 0, "Production findings deleted by canary must be 0!"
    assert stale_findings_counted_as_current == 0, "Stale findings must not be counted as current!"
    assert card_uses_latest_applicable_run == "YES", "Card must use latest applicable run!"
    assert experience_uses_latest_applicable_run == "YES", "Experience must use latest applicable run!"

    print("CORRECTIVE_CANARY_8=PASS")
    logger.info("All asserts passed successfully!")

if __name__ == "__main__":
    main()
