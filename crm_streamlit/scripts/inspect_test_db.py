from src.services.db_bootstrap import connect_databases

def main():
    _, t, c, _ = connect_databases()
    if c:
        print("TRACES:")
        traces = c.execute_query("SELECT id, attempt_count, consensus_state, research_completeness, document_set_hash, extracted_evidence_hash FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000700")
        for tr in traces:
            print(tr)
    if t:
        print("QUEUE:")
        queue = t.execute_query("SELECT id, procurement_id, pipeline_generation, status FROM document_processing_queue WHERE procurement_id = 900000700")
        for q in queue:
            print(q)
        print("FILES:")
        files = t.execute_query("SELECT id, file_name, download_status, url, url_hash FROM document_files WHERE procurement_id = 900000700")
        for f in files:
            print(f)

if __name__ == '__main__':
    main()
