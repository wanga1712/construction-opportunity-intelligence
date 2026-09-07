import sys
import psycopg2
from psycopg2.extras import RealDictCursor

def main():
    print("=== STRUCTURED FACT DAMAGE AUDIT (READ-ONLY) ===")
    conn = psycopg2.connect("dbname=document_intelligence user=postgres host=/var/run/postgresql")
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Audit before purge
    cur.execute("""
        SELECT COUNT(*) AS synthetic_runs
        FROM structured_extraction_runs
        WHERE source_text_snapshot LIKE 'Спецификация материалов%'
           OR (source_validator_name = 'context_validator' AND source_validator_version = 'v4');
    """)
    synthetic_runs = cur.fetchone()['synthetic_runs']

    cur.execute("""
        SELECT COUNT(*) AS synthetic_entities
        FROM structured_entities
        WHERE run_id IN (
            SELECT id FROM structured_extraction_runs
            WHERE source_text_snapshot LIKE 'Спецификация материалов%'
               OR (source_validator_name = 'context_validator' AND source_validator_version = 'v4')
        );
    """)
    synthetic_entities = cur.fetchone()['synthetic_entities']

    print(f"Audit only: {synthetic_runs} synthetic runs, {synthetic_entities} synthetic entities found.")
    print("READ_ONLY_AUDIT = YES")
    print("DESTRUCTIVE_DELETE = NO")
    print("DESTRUCTIVE_TRUNCATE = NO")

    # 2. Audit remaining entities trust state breakdown
    cur.execute("SELECT structured_fact_trust_state, count(*) FROM structured_entities GROUP BY structured_fact_trust_state;")
    print("Remaining structured_entities trust states:")
    for r in cur.fetchall():
        print(dict(r))

if __name__ == "__main__":
    main()
