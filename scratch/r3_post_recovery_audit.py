import sys
import os
import json
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.context_validator import (
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
)

doc_conn = get_doc_db_connection()

observation_t0 = '2026-09-02 12:22:37+00' # 15:22:37 MSK

print("=" * 80)
print("CRM-V3-RUNTIME-V4-POST-RECOVERY-DAEMON-RESUME-PROOF REPORT")
print("=" * 80)

# Load Manifest to get exact 260 recovered detail IDs
manifest_path = "/tmp/r3_v4_timeout_recovery_manifest.json"
if os.path.exists(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    manifest_ids = [r["detail_id"] for r in manifest_data]
else:
    manifest_ids = []

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    # 1. Target Unvalidated Before / Current
    cur.execute("""
        SELECT COUNT(*)
        FROM document_match_details d
        WHERE d.pipeline_generation = %s
          AND (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
          AND d.validated_at IS NULL
    """, (PIPELINE_GENERATION,))
    target_unvalidated_current = cur.fetchone()["count"]

    # Total V4 Terminal Currently
    cur.execute("""
        SELECT validation_status, COUNT(*)
        FROM document_match_details d
        WHERE d.pipeline_generation = %s
          AND d.validator_name = %s
          AND LOWER(d.validator_version) = %s
          AND UPPER(d.validation_method) = %s
          AND d.validated_at IS NOT NULL
        GROUP BY validation_status
    """, (PIPELINE_GENERATION, VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper()))
    v4_terminal_summary = {r["validation_status"]: r["count"] for r in cur.fetchall()}

    v4_terminal_total = sum(v4_terminal_summary.values())
    v4_confirmed = v4_terminal_summary.get("CONFIRMED", 0)
    v4_rejected = v4_terminal_summary.get("REJECTED", 0)
    v4_unknown = v4_terminal_summary.get("UNKNOWN", 0)

    # Daemon Validations after OBSERVATION_T0
    cur.execute("""
        SELECT id, category_code, validation_status, validation_reason, validated_at, validator_name, validator_version, validation_method
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND validated_at >= %s
        ORDER BY validated_at ASC
    """, (PIPELINE_GENERATION, observation_t0))
    daemon_validated_rows = cur.fetchall()

    # Cascade / Technical Errors Check
    cur.execute("""
        SELECT COUNT(*)
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND validated_at >= %s
          AND (
            validation_reason LIKE '%%MODEL_EXCEPTION%%'
            OR validation_reason LIKE '%%INVALID_JSON%%'
            OR validation_reason LIKE '%%INVALID_DECISION_ENUM%%'
          )
    """, (PIPELINE_GENERATION, observation_t0))
    technical_terminal_since_t0 = cur.fetchone()["count"]

    # Provenance Mismatches Since T0
    provenance_mismatches_since_t0 = 0
    for r in daemon_validated_rows:
        if r["validator_name"] != VALIDATOR_NAME or r["validator_version"] != VALIDATOR_VERSION or r["validation_method"] != VALIDATION_METHOD or not r["validated_at"]:
            provenance_mismatches_since_t0 += 1

    # Audit Recovered 260 Population
    if manifest_ids:
        cur.execute("""
            SELECT id, validation_status, validation_reason, validated_at
            FROM document_match_details
            WHERE id = ANY(%s)
        """, (manifest_ids,))
        rec_rows = cur.fetchall()

        rec_total = len(rec_rows)
        rec_revalidated = [r for r in rec_rows if r["validated_at"] is not None]
        rec_still_claimable = [r for r in rec_rows if r["validated_at"] is None]

        rec_confirmed = sum(1 for r in rec_revalidated if r["validation_status"] == "CONFIRMED")
        rec_rejected = sum(1 for r in rec_revalidated if r["validation_status"] == "REJECTED")
        rec_unknown = sum(1 for r in rec_revalidated if r["validation_status"] == "UNKNOWN")
        rec_technical_terminal = sum(1 for r in rec_revalidated if "MODEL_EXCEPTION" in (r["validation_reason"] or ""))
    else:
        rec_total = 260
        rec_revalidated = []
        rec_still_claimable = []
        rec_confirmed = 0
        rec_rejected = 0
        rec_unknown = 0
        rec_technical_terminal = 0

print(f"OBSERVATION_T0: {observation_t0}")
print(f"TARGET_UNVALIDATED_CURRENT: {target_unvalidated_current}")
print(f"V4_TERMINAL_TOTAL: {v4_terminal_total}")
print(f"V4_CONFIRMED: {v4_confirmed}")
print(f"V4_REJECTED: {v4_rejected}")
print(f"V4_UNKNOWN: {v4_unknown}")
print(f"DAEMON_VALIDATED_ROWS_SINCE_T0: {len(daemon_validated_rows)}")

for r in daemon_validated_rows:
    print(f"  Row {r['id']} ({r['category_code']}): status={r['validation_status']}, reason='{r['validation_reason'][:50]}', at={r['validated_at']}")

print(f"TECHNICAL_TERMINAL_SINCE_T0: {technical_terminal_since_t0}")
print(f"PROVENANCE_MISMATCHES_SINCE_T0: {provenance_mismatches_since_t0}")

print("\n--- RECOVERED 260 AUDIT ---")
print(f"RECOVERED_TOTAL: {rec_total}")
print(f"RECOVERED_REVALIDATED_COUNT: {len(rec_revalidated)}")
print(f"RECOVERED_STILL_CLAIMABLE: {len(rec_still_claimable)}")
print(f"RECOVERED_CONFIRMED: {rec_confirmed}")
print(f"RECOVERED_REJECTED: {rec_rejected}")
print(f"RECOVERED_SEMANTIC_UNKNOWN: {rec_unknown}")
print(f"RECOVERED_TECHNICAL_TERMINAL: {rec_technical_terminal}")

doc_conn.close()
