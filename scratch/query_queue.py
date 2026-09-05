import psycopg2
import sys

def run():
    conn = psycopg2.connect("host=127.0.0.1 dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT")
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, procurement_id, status, pipeline_generation, temporal_class, created_at, completed_at
        FROM document_processing_queue 
        WHERE status = 'PRE_RESEARCH_WAITING'
        ORDER BY id DESC;
    """)
    print("=== PRE_RESEARCH_WAITING rows ===")
    for row in cur.fetchall():
        print(f"ID: {row[0]}, ProcID: {row[1]}, Status: {row[2]}, Gen: {row[3]}, Class: {row[4]}, Created: {row[5]}, Completed: {row[6]}")
        
    conn.close()

if __name__ == "__main__":
    run()
