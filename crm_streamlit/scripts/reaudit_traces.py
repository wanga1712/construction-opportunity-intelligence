"""Re-audit existing traces in crm_v3_autonomous_analysis_traces."""
import os
import sys
import psycopg2
import psycopg2.extras

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases

def main():
    _, _, crm_db, _ = connect_databases()
    
    # Connection to doc DB on localhost
    pwd_env = os.getenv("S13_DOCUMENT_DB_PASSWORD")
    if not pwd_env:
        raise ValueError("S13_DOCUMENT_DB_PASSWORD environment variable not set")
    doc_conn = psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=pwd_env
    )
    
    # 1. Fetch all traces
    traces = crm_db.execute_query("SELECT id, procurement_id FROM crm_v3_autonomous_analysis_traces") or []
    
    print(f"Re-auditing {len(traces)} traces...")
    for t in traces:
        tid = t["id"]
        pid = t["procurement_id"]
        
        # Query files for this procurement
        with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT f.download_status, r.status AS parse_status
                FROM document_files f
                LEFT JOIN document_processing_results r ON r.file_id = f.id
                WHERE f.procurement_id = %s
                """,
                (pid,)
            )
            files = cur.fetchall() or []
            
        completeness = "COMPLETE"
        for f in files:
            download_status = f.get("download_status")
            parse_status = f.get("parse_status")
            
            state = "SEARCHED"
            if download_status in ("FAILED", "ERROR", "DOWNLOAD_FAILED"):
                state = "DOWNLOAD_FAILED"
            elif parse_status in ("FAILED", "ERROR", "PARSE_FAILED"):
                state = "PARSE_FAILED"
            elif parse_status in ("UNSUPPORTED", "UNSUPPORTED_FORMAT"):
                state = "UNSUPPORTED_FORMAT"
            elif parse_status in ("EMPTY", "EMPTY_DOCUMENT"):
                state = "EMPTY_DOCUMENT"
                
            if state in ("DOWNLOAD_FAILED", "PARSE_FAILED", "UNREADABLE", "PARTIALLY_SEARCHED", "UNSUPPORTED_FORMAT"):
                completeness = "PARTIAL"
                break
                
        # Update trace
        crm_db.execute_update(
            "UPDATE crm_v3_autonomous_analysis_traces SET research_completeness = %s WHERE id = %s",
            (completeness, tid)
        )
        
    doc_conn.close()
    print("Trace re-audit completed successfully.")

if __name__ == "__main__":
    main()
