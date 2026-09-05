#!/usr/bin/env python3
"""
Applies R3-4E-B strict legacy evidence provenance closure to context_validator_service.py.
"""
import os

SERVICE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

with open(SERVICE_PATH, "r", encoding="utf-8") as f:
    src = f.read()

old_rebuild = '''def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
    """Rebuilds document_evidence ONLY for affected procurement/category pairs.

    Truthful evidence provenance policy (R3-4E-A):
    - If current v2 CONFIRMED details exist:
      Build document_evidence strictly from v2 CONFIRMED details.
      match_count = len(v2_rows)
      evidence_score = max(score for r in v2_rows)
      validation_version = "v2"
      validation_method = "QWEN_CONTEXT_V2"
      Legacy v1 rows remain stored in document_match_details but do NOT contribute to v2 score/count.
    - Else if legacy v1 CONFIRMED details exist:
      Build document_evidence strictly from v1 CONFIRMED details.
      match_count = len(v1_rows)
      evidence_score = max(score for r in v1_rows)
      validation_version = "v1"
      validation_method = "QWEN_CONTEXT_V1"
    - Else (0 confirmed details):
      DELETE from document_evidence.
    """
    if not affected:
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected:
            cur.execute("""
                SELECT d.score, m.queue_id, d.validator_version, d.validation_method
                FROM document_match_details d
                JOIN document_matches m ON d.match_id = m.id
                WHERE d.procurement_id = %s
                  AND d.category_code = %s
                  AND d.pipeline_generation = %s
                  AND d.validation_status = 'CONFIRMED'
            """, (pid, cat, PIPELINE_GENERATION))
            confirmed_rows = cur.fetchall()

            if not confirmed_rows:
                cur.execute("""
                    DELETE FROM document_evidence
                    WHERE procurement_id = %s
                      AND category_code = %s
                      AND pipeline_generation = %s
                """, (pid, cat, PIPELINE_GENERATION))
                continue

            # Explicit provenance check for v2 confirmed rows
            v2_rows = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v2"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V2"
            ]

            if v2_rows:
                target_rows = v2_rows
                val_ver = "v2"
                val_method = "QWEN_CONTEXT_V2"
            else:
                target_rows = confirmed_rows
                val_ver = "v1"
                val_method = "QWEN_CONTEXT_V1"

            max_score = max(float(r["score"]) for r in target_rows)
            match_count = len(target_rows)
            queue_id = target_rows[0]["queue_id"]

            cur.execute("""
                INSERT INTO document_evidence
                (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (procurement_id, category_code, pipeline_generation)
                DO UPDATE SET
                    evidence_score = EXCLUDED.evidence_score,
                    match_count = EXCLUDED.match_count,
                    validation_status = 'CONFIRMED',
                    validation_version = EXCLUDED.validation_version,
                    validation_method = EXCLUDED.validation_method
            """, (
                pid, queue_id, cat, max_score, match_count,
                "STRUCTURED_EXTRACTION_PENDING", "CONFIRMED", val_ver, val_method,
                PIPELINE_GENERATION
            ))

    conn.commit()'''

new_rebuild = '''def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
    """Rebuilds document_evidence ONLY for affected procurement/category pairs.

    Strict explicit evidence provenance policy (R3-4E-B):
    - V2_TRUSTED: validator_version='v2' AND validation_method='QWEN_CONTEXT_V2'
    - V1_TRUSTED: validator_version='v1' AND validation_method='QWEN_CONTEXT_V1'
    - UNTRUSTED/MISSING: Untrusted or missing provenance rows NEVER create positive evidence.

    Selection precedence:
    1. If v2 trusted CONFIRMED rows exist -> aggregate ONLY v2 trusted rows (version='v2', method='QWEN_CONTEXT_V2').
    2. Else if v1 trusted CONFIRMED rows exist -> aggregate ONLY v1 trusted rows (version='v1', method='QWEN_CONTEXT_V1').
    3. Else (0 trusted confirmed rows) -> DELETE from document_evidence.
    """
    if not affected:
        return

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected:
            cur.execute("""
                SELECT d.score, m.queue_id, d.validator_version, d.validation_method
                FROM document_match_details d
                JOIN document_matches m ON d.match_id = m.id
                WHERE d.procurement_id = %s
                  AND d.category_code = %s
                  AND d.pipeline_generation = %s
                  AND d.validation_status = 'CONFIRMED'
            """, (pid, cat, PIPELINE_GENERATION))
            confirmed_rows = cur.fetchall()

            if not confirmed_rows:
                cur.execute("""
                    DELETE FROM document_evidence
                    WHERE procurement_id = %s
                      AND category_code = %s
                      AND pipeline_generation = %s
                """, (pid, cat, PIPELINE_GENERATION))
                continue

            v2_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v2"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V2"
            ]

            v1_trusted = [
                r for r in confirmed_rows
                if str(r.get("validator_version") or "").lower() == "v1"
                and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V1"
            ]

            if v2_trusted:
                target_rows = v2_trusted
                val_ver = "v2"
                val_method = "QWEN_CONTEXT_V2"
            elif v1_trusted:
                target_rows = v1_trusted
                val_ver = "v1"
                val_method = "QWEN_CONTEXT_V1"
            else:
                cur.execute("""
                    DELETE FROM document_evidence
                    WHERE procurement_id = %s
                      AND category_code = %s
                      AND pipeline_generation = %s
                """, (pid, cat, PIPELINE_GENERATION))
                continue

            max_score = max(float(r["score"]) for r in target_rows)
            match_count = len(target_rows)
            queue_id = target_rows[0]["queue_id"]

            cur.execute("""
                INSERT INTO document_evidence
                (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (procurement_id, category_code, pipeline_generation)
                DO UPDATE SET
                    evidence_score = EXCLUDED.evidence_score,
                    match_count = EXCLUDED.match_count,
                    validation_status = 'CONFIRMED',
                    validation_version = EXCLUDED.validation_version,
                    validation_method = EXCLUDED.validation_method
            """, (
                pid, queue_id, cat, max_score, match_count,
                "STRUCTURED_EXTRACTION_PENDING", "CONFIRMED", val_ver, val_method,
                PIPELINE_GENERATION
            ))

    conn.commit()'''

assert old_rebuild in src, "old_rebuild not found in service"
src = src.replace(old_rebuild, new_rebuild, 1)

with open(SERVICE_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Applied R3-4E-B strict provenance patch to context_validator_service.py")
