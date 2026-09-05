import psycopg2
import sys

def run():
    try:
        conn = psycopg2.connect("host=127.0.0.1 dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT")
        print("Success 1 (doc_worker)")
        conn.close()
    except Exception as e:
        print("Fail 1:", e)
        
    try:
        conn = psycopg2.connect("host=127.0.0.1 dbname=document_intelligence user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX")
        print("Success 2 (crm_app)")
        conn.close()
    except Exception as e:
        print("Fail 2:", e)

if __name__ == "__main__":
    run()
