"""DB-backed one-detail smoke for Phase A; never applies trust."""

import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_structured_fact_canary import main as run_extract_phase


def main():
    result = run_extract_phase(limit=1)
    assert result["runs"] == 1, "EXPECTED_ONE_PERSISTED_RUN=NO"
    assert result["model_call_attempted"] == 1, "EXPECTED_ONE_REAL_MODEL_CALL=NO"

    conn = psycopg2.connect("dbname=document_intelligence user=postgres host=/var/run/postgresql")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    r.id AS run_id,
                    r.source_text_snapshot,
                    r.source_available,
                    r.extraction_eligible,
                    d.validation_status,
                    COUNT(e.id) AS entity_count,
                    COUNT(e.id) FILTER (WHERE e.structured_fact_trust_state = 'TRUSTED_PRODUCTION') AS trusted_count,
                    COUNT(e.id) FILTER (WHERE e.structured_fact_trust_state = 'QUALITY_REJECTED') AS rejected_count,
                    r.structured_fact_trust_state AS run_trust_state
                FROM structured_extraction_runs r
                JOIN document_match_details d ON d.id = r.detail_id
                LEFT JOIN structured_entities e ON e.run_id = r.id
                WHERE r.canary_batch_id = %s
                GROUP BY r.id, d.validation_status
            """, (result["batch_id"],))
            row = cur.fetchone()
            assert row is not None, "RUN_PERSISTED=NO"
            assert row["validation_status"] is not None, "CANDIDATE_ROW_HAS_VALIDATION_STATUS=NO"
            assert row["source_text_snapshot"], "SNAPSHOT_NON_EMPTY=NO"
            assert row["source_available"] is True, "AUTHORITY_ACCEPTED=NO"
            assert row["extraction_eligible"] is True, "EXTRACTION_ELIGIBLE=NO"
            assert row["trusted_count"] == 0, "TRUSTED_PRODUCTION_BEFORE_REVIEW=NONZERO"
            assert row["rejected_count"] == 0, "QUALITY_REJECTED_BEFORE_REVIEW=NONZERO"
            assert row["run_trust_state"] == "CANARY_PENDING_REVIEW", "RUN_NOT_PENDING_BEFORE_REVIEW"
            print("CANDIDATE_ROW_HAS_VALIDATION_STATUS=YES")
            print("SNAPSHOT_NON_EMPTY=YES")
            print("AUTHORITY_ACCEPTED=YES")
            print("EXACTLY_ONE_REAL_MODEL_CALL_ATTEMPTED=YES")
            print("RUN_PERSISTED=YES")
            print("TRUSTED_PRODUCTION_BEFORE_REVIEW=0")
            print("QUALITY_REJECTED_BEFORE_REVIEW=0")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(str(exc), file=sys.stderr)
        raise
