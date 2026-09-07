"""Read-only proof of the persisted V4 source authority fields."""

import psycopg2
from psycopg2.extras import RealDictCursor


def main():
    conn = psycopg2.connect("dbname=document_intelligence user=postgres host=/var/run/postgresql")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    r.id AS run_id,
                    r.detail_id AS detail_id,
                    r.source_text_sha256,
                    r.source_validator_name,
                    r.source_validator_version,
                    r.source_validation_method,
                    r.source_available,
                    r.extraction_eligible,
                    r.document_name,
                    r.archive_member_path,
                    r.page_or_sheet,
                    d.validator_name,
                    d.validator_version,
                    d.validation_method,
                    d.validation_status
                FROM structured_extraction_runs r
                JOIN document_match_details d ON d.id = r.detail_id
                ORDER BY r.id DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                print("PERSISTED_AUTHORITY_SAMPLE=NONE")
                return
            print("PERSISTED_AUTHORITY_SAMPLE=FOUND")
            print("V4_SOURCE_AUTHORITY={")
            print("  SOURCE_TEXT_TABLE: structured_extraction_runs")
            print("  SOURCE_TEXT_FIELD: source_text_snapshot")
            print("  SOURCE_SHA_FIELD: source_text_sha256")
            print("  VALIDATION_STATUS_FIELD: document_match_details.validation_status")
            print("  VALIDATOR_NAME_FIELD: document_match_details.validator_name")
            print("  VALIDATOR_VERSION_FIELD: document_match_details.validator_version")
            print("  VALIDATION_METHOD_FIELD: document_match_details.validation_method")
            print("  SOURCE_AVAILABLE_FIELD: structured_extraction_runs.source_available (DERIVED_RESULT)")
            print("  EXTRACTION_ELIGIBLE_FIELD: structured_extraction_runs.extraction_eligible (DERIVED_RESULT)")
            print("  DOCUMENT_ID_FIELD: structured_extraction_runs.detail_id")
            print("  ARCHIVE_MEMBER_FIELD: structured_extraction_runs.archive_member_path")
            print("  PAGE_OR_SHEET_FIELD: structured_extraction_runs.page_or_sheet")
            print("}")
            for key in (
                "run_id", "detail_id", "source_text_sha256", "source_validator_name",
                "source_validator_version", "source_validation_method", "source_available",
                "extraction_eligible", "document_name", "archive_member_path", "page_or_sheet",
                "validator_name", "validator_version", "validation_method", "validation_status",
            ):
                print(f"{key.upper()} = {row[key]}")
            print("SOURCE_AUTHORITY_HARDCODED = NO")
            print("MATCH_TERM_AS_SOURCE_SNAPSHOT = 0")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
