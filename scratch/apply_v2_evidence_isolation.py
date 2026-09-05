#!/usr/bin/env python3
"""
Applies R3-4E-A v2 evidence provenance isolation to context_validator_service.py.
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

old_update_validations = '''def update_candidate_validations(conn, results: List[Dict[str, Any]]) -> Set[Tuple[int, str]]:
    """Updates document_match_details with validation outcomes."""
    affected: Set[Tuple[int, str]] = set()
    if not results:
        return affected

    with conn.cursor() as cur:
        for r in results:
            detail_id = r["detail_id"]
            status = r["decision"]
            method = r.get("validation_method", "QWEN_CONTEXT_V1")
            reason = f"[{r.get('reason_code', 'UNSPECIFIED')}] {r.get('reason', '')}"
            val_name = r.get("validator_name", "context_validator")
            val_ver = r.get("validator_version", "v1")

            cur.execute("""
                UPDATE document_match_details
                SET validation_status = %s,
                    validation_method = %s,
                    validation_reason = %s,
                    validated_at = NOW(),
                    validator_name = %s,
                    validator_version = %s
                WHERE id = %s
            """, (status, method, reason, val_name, val_ver, detail_id))

            affected.add((r["procurement_id"], r["category_code"]))

    conn.commit()
    return affected'''

new_update_validations = '''def update_candidate_validations(conn, results: List[Dict[str, Any]]) -> Set[Tuple[int, str]]:
    """Updates document_match_details with validation outcomes.

    Strict provenance enforcement: CONFIRMED results missing explicit validator provenance
    are demoted to UNKNOWN to prevent fake v1/v2 evidence creation.
    """
    affected: Set[Tuple[int, str]] = set()
    if not results:
        return affected

    with conn.cursor() as cur:
        for r in results:
            detail_id = r["detail_id"]
            status = r["decision"]
            method = r.get("validation_method")
            val_name = r.get("validator_name")
            val_ver = r.get("validator_version")

            if status == "CONFIRMED" and (not val_name or not val_ver or not method):
                status = "UNKNOWN"
                reason = "[MISSING_VALIDATOR_PROVENANCE] Missing explicit validator provenance attributes"
                method = "UNSPECIFIED"
                val_name = "context_validator"
                val_ver = "UNKNOWN"
            else:
                method = method or "QWEN_CONTEXT_V2"
                val_name = val_name or "context_validator"
                val_ver = val_ver or "v2"
                reason = f"[{r.get('reason_code', 'UNSPECIFIED')}] {r.get('reason', '')}"

            cur.execute("""
                UPDATE document_match_details
                SET validation_status = %s,
                    validation_method = %s,
                    validation_reason = %s,
                    validated_at = NOW(),
                    validator_name = %s,
                    validator_version = %s
                WHERE id = %s
            """, (status, method, reason, val_name, val_ver, detail_id))

            affected.add((r["procurement_id"], r["category_code"]))

    conn.commit()
    return affected'''

assert old_update_validations in src, "old_update_validations not found"
src = src.replace(old_update_validations, new_update_validations, 1)

old_rebuild = '''def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
    """Rebuilds document_evidence ONLY for affected procurement/category pairs.

    Truthful version provenance: if any confirmed row in the group was validated with v2,
    the resulting evidence record uses validation_version='v2', validation_method='QWEN_CONTEXT_V2'.
    Otherwise if only legacy v1 confirmed rows exist, retains 'v1', 'QWEN_CONTEXT_V1'.
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

            if confirmed_rows:
                max_score = max(float(r["score"]) for r in confirmed_rows)
                match_count = len(confirmed_rows)
                queue_id = confirmed_rows[0]["queue_id"]

                has_v2 = any(
                    str(r.get("validator_version") or "").lower() == "v2"
                    or "V2" in str(r.get("validation_method") or "").upper()
                    for r in confirmed_rows
                )
                val_ver = "v2" if has_v2 else "v1"
                val_method = "QWEN_CONTEXT_V2" if has_v2 else "QWEN_CONTEXT_V1"

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
            else:
                cur.execute("""
                    DELETE FROM document_evidence
                    WHERE procurement_id = %s
                      AND category_code = %s
                      AND pipeline_generation = %s
                """, (pid, cat, PIPELINE_GENERATION))

    conn.commit()'''

new_rebuild = '''def rebuild_affected_evidence(conn, affected: Set[Tuple[int, str]]) -> None:
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

assert old_rebuild in src, "old_rebuild not found"
src = src.replace(old_rebuild, new_rebuild, 1)

with open(SERVICE_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Applied v2 evidence isolation patch to context_validator_service.py")
