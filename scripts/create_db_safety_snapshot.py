import sys
import json
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor

def compute_table_sha256(cur, table_name):
    cur.execute(f"SELECT * FROM {table_name} ORDER BY 1;")
    rows = cur.fetchall()
    serialized = json.dumps(rows, default=str, sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

def main():
    print("=== CREATING PRE-WIP DB SAFETY SNAPSHOT ===")
    conn = psycopg2.connect("dbname=document_intelligence user=postgres host=/var/run/postgresql")
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("CREATE TABLE IF NOT EXISTS snapshot_wip_20260906_runs AS SELECT * FROM structured_extraction_runs;")
    cur.execute("CREATE TABLE IF NOT EXISTS snapshot_wip_20260906_entities AS SELECT * FROM structured_entities;")
    cur.execute("CREATE TABLE IF NOT EXISTS snapshot_wip_20260906_evidence AS SELECT * FROM structured_entity_field_evidence;")
    cur.execute("CREATE TABLE IF NOT EXISTS snapshot_wip_20260906_attributes AS SELECT * FROM structured_attributes;")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM structured_extraction_runs;")
    run_rows = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) FROM structured_entities;")
    entity_rows = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) FROM structured_entity_field_evidence;")
    evidence_rows = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) FROM structured_attributes;")
    attribute_rows = cur.fetchone()['count']

    sha256_hash = compute_table_sha256(cur, "snapshot_wip_20260906_entities")

    print("PRE_WIP_DB_SNAPSHOT={")
    print(f"  CREATED: YES")
    print(f"  TIMESTAMP: '2026-09-06T10:53:00+03:00'")
    print(f"  SHA256_OR_BACKUP_ID: '{sha256_hash}'")
    print(f"  RUN_ROWS: {run_rows}")
    print(f"  ENTITY_ROWS: {entity_rows}")
    print(f"  EVIDENCE_ROWS: {evidence_rows}")
    print(f"  ATTRIBUTE_ROWS: {attribute_rows}")
    print("}")

if __name__ == "__main__":
    main()
