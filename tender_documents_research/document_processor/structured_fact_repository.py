"""
R4 Structured Product Fact Repository.
Provides database persistence and retrieval for ExtractionRun, StructuredEntity,
StructuredFieldEvidence, and StructuredAttribute in PostgreSQL document_intelligence DB.
Enforces contract validation BEFORE DML, value-bound provenance, run immutability, stable child IDs, and caller-owned transactions.
"""

from typing import Any, Dict, List, Optional
import psycopg2.extras

from tender_documents_research.document_processor.structured_fact_contract import (
    ExtractionRun,
    StructuredEntity,
    StructuredFieldEvidence,
    StructuredAttribute,
    STRUCTURED_EXTRACTOR_VERSION,
    ExtractionRunIdentityConflict,
    validate_extraction_run,
)

def save_extraction_run(conn, run: ExtractionRun) -> int:
    """
    Persists an ExtractionRun along with its child entities, field evidence, and attributes.
    
    Invariants:
    1. Calls validate_extraction_run(run) BEFORE any DML. Raises ValueError if invalid. (INVALID_RUN_WRITES=0)
    2. Checks run immutability for existing (detail_id, extractor_version). Raises ExtractionRunIdentityConflict if input/prompt changed.
    3. Preserves child entity/attribute/evidence IDs on identical repeated save (REPEATED_IDENTICAL_SAVE_STABLE_IDS=YES).
    4. Does NOT commit internally. Caller owns transaction.
    """
    # 1. Pre-DML Contract Validation (Section 21)
    is_valid, errors = validate_extraction_run(run)
    if not is_valid:
        raise ValueError(f"Contract Validation Failed: {', '.join(errors)}")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # 2. Check Run Immutability (Section 14)
        cur.execute("""
            SELECT * FROM structured_extraction_runs
            WHERE detail_id = %s AND extractor_version = %s
        """, (run.detail_id, run.extractor_version))
        existing_run = cur.fetchone()

        if existing_run:
            # Verify immutable inputs match
            immutable_checks = [
                ("source_text_sha256", run.source_text_sha256),
                ("source_validator_name", run.source_validator_name),
                ("source_validator_version", run.source_validator_version),
                ("source_validation_method", run.source_validation_method),
                ("extractor_name", run.extractor_name),
                ("extractor_version", run.extractor_version),
                ("extraction_method", run.extraction_method),
                ("prompt_version", run.prompt_version),
                ("model_name", run.model_name),
                ("category_code", run.category_code),
                ("subcategory_code", run.subcategory_code),
            ]
            for col_name, expected_val in immutable_checks:
                actual_val = existing_run.get(col_name)
                if actual_val != expected_val:
                    raise ExtractionRunIdentityConflict(
                        f"Run identity conflict for detail_id {run.detail_id}: "
                        f"col '{col_name}' existing '{actual_val}' != new '{expected_val}'"
                    )

            run_id = existing_run["id"]
            cur.execute("""
                UPDATE structured_extraction_runs SET
                    status = %s,
                    raw_response = %s,
                    error_code = %s,
                    error_message = %s,
                    completed_at = NOW()
                WHERE id = %s
            """, (
                run.status,
                psycopg2.extras.Json(run.raw_response) if run.raw_response is not None else None,
                run.error_code, run.error_message,
                run_id
            ))
        else:
            cur.execute("""
                INSERT INTO structured_extraction_runs (
                    detail_id, match_id, procurement_id, queue_id,
                    category_code, subcategory_code, document_name, archive_member_path,
                    page_or_sheet, row_number, source_text_snapshot, source_text_sha256,
                    source_validator_name, source_validator_version, source_validation_method,
                    extractor_name, extractor_version, extraction_method, prompt_version,
                    model_name, status, raw_response, error_code, error_message, completed_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, NOW()
                )
                RETURNING id
            """, (
                run.detail_id, run.match_id, run.procurement_id, run.queue_id,
                run.category_code, run.subcategory_code, run.document_name, run.archive_member_path,
                run.page_or_sheet, run.row_number, run.source_text_snapshot, run.source_text_sha256,
                run.source_validator_name, run.source_validator_version, run.source_validation_method,
                run.extractor_name, run.extractor_version, run.extraction_method, run.prompt_version,
                run.model_name, run.status,
                psycopg2.extras.Json(run.raw_response) if run.raw_response is not None else None,
                run.error_code, run.error_message
            ))
            run_id = cur.fetchone()["id"]

        # 3. Preserve Stable Child Identities (Section 23)
        cur.execute("SELECT id, entity_fingerprint FROM structured_entities WHERE run_id = %s", (run_id,))
        existing_entities = {r["entity_fingerprint"]: r["id"] for r in cur.fetchall()}
        current_entity_fingerprints = set()

        for ent in run.entities:
            current_entity_fingerprints.add(ent.entity_fingerprint)
            if ent.entity_fingerprint in existing_entities:
                entity_id = existing_entities[ent.entity_fingerprint]
                cur.execute("""
                    UPDATE structured_entities SET
                        confidence = %s,
                        product_name_normalized = %s,
                        manufacturer_normalized = %s,
                        brand_normalized = %s,
                        product_line_normalized = %s,
                        model_article_normalized = %s,
                        quantity_raw = %s,
                        quantity_value = %s,
                        quantity_unit_raw = %s,
                        quantity_unit_normalized = %s,
                        unit_price_raw = %s,
                        unit_price_value = %s,
                        total_price_raw = %s,
                        total_price_value = %s,
                        currency_raw = %s,
                        currency_code = %s
                    WHERE id = %s
                """, (
                    ent.confidence, ent.product_name_normalized,
                    ent.manufacturer_normalized, ent.brand_normalized,
                    ent.product_line_normalized, ent.model_article_normalized,
                    ent.quantity_raw, ent.quantity_value, ent.quantity_unit_raw, ent.quantity_unit_normalized,
                    ent.unit_price_raw, ent.unit_price_value,
                    ent.total_price_raw, ent.total_price_value,
                    ent.currency_raw, ent.currency_code,
                    entity_id
                ))
            else:
                cur.execute("""
                    INSERT INTO structured_entities (
                        run_id, detail_id, procurement_id, category_code, subcategory_code,
                        entity_fingerprint, entity_type,
                        manufacturer_raw, manufacturer_normalized,
                        brand_raw, brand_normalized,
                        product_line_raw, product_line_normalized,
                        product_name_raw, product_name_normalized,
                        model_article_raw, model_article_normalized,
                        quantity_raw, quantity_value, quantity_unit_raw, quantity_unit_normalized,
                        unit_price_raw, unit_price_value,
                        total_price_raw, total_price_value,
                        currency_raw, currency_code,
                        source_quote, confidence
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s
                    )
                    RETURNING id
                """, (
                    run_id, run.detail_id, run.procurement_id, run.category_code, run.subcategory_code,
                    ent.entity_fingerprint, ent.entity_type,
                    ent.manufacturer_raw, ent.manufacturer_normalized,
                    ent.brand_raw, ent.brand_normalized,
                    ent.product_line_raw, ent.product_line_normalized,
                    ent.product_name_raw, ent.product_name_normalized,
                    ent.model_article_raw, ent.model_article_normalized,
                    ent.quantity_raw, ent.quantity_value, ent.quantity_unit_raw, ent.quantity_unit_normalized,
                    ent.unit_price_raw, ent.unit_price_value,
                    ent.total_price_raw, ent.total_price_value,
                    ent.currency_raw, ent.currency_code,
                    ent.source_quote, ent.confidence
                ))
                entity_id = cur.fetchone()["id"]

            # Field Evidence Persistence
            cur.execute("SELECT id, evidence_fingerprint FROM structured_entity_field_evidence WHERE entity_id = %s", (entity_id,))
            existing_ev = {r["evidence_fingerprint"]: r["id"] for r in cur.fetchall()}
            current_ev_fingerprints = set()

            for fe in ent.field_evidence:
                current_ev_fingerprints.add(fe.evidence_fingerprint)
                if fe.evidence_fingerprint not in existing_ev:
                    cur.execute("""
                        INSERT INTO structured_entity_field_evidence (
                            entity_id, run_id, field_name, source_quote, evidence_fingerprint
                        ) VALUES (%s, %s, %s, %s, %s)
                    """, (entity_id, run_id, fe.field_name, fe.source_quote, fe.evidence_fingerprint))

            stale_ev_ids = [eid for fp, eid in existing_ev.items() if fp not in current_ev_fingerprints]
            if stale_ev_ids:
                cur.execute("DELETE FROM structured_entity_field_evidence WHERE id = ANY(%s)", (stale_ev_ids,))

            # Attributes Persistence
            cur.execute("SELECT id, attribute_fingerprint FROM structured_attributes WHERE entity_id = %s", (entity_id,))
            existing_attrs = {r["attribute_fingerprint"]: r["id"] for r in cur.fetchall()}
            current_attr_fingerprints = set()

            for attr in ent.attributes:
                current_attr_fingerprints.add(attr.attribute_fingerprint)
                if attr.attribute_fingerprint in existing_attrs:
                    cur.execute("""
                        UPDATE structured_attributes SET
                            confidence = %s,
                            normalized_value = %s,
                            numeric_value = %s,
                            unit_raw = %s,
                            unit_normalized = %s
                        WHERE id = %s
                    """, (
                        attr.confidence, attr.normalized_value, attr.numeric_value,
                        attr.unit_raw, attr.unit_normalized,
                        existing_attrs[attr.attribute_fingerprint]
                    ))
                else:
                    cur.execute("""
                        INSERT INTO structured_attributes (
                            entity_id, run_id, attribute_fingerprint,
                            attribute_name, attribute_name_normalized,
                            raw_value, normalized_value, numeric_value,
                            unit_raw, unit_normalized, source_quote, confidence
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s
                        )
                    """, (
                        entity_id, run_id, attr.attribute_fingerprint,
                        attr.attribute_name, attr.attribute_name_normalized,
                        attr.raw_value, attr.normalized_value, attr.numeric_value,
                        attr.unit_raw, attr.unit_normalized, attr.source_quote, attr.confidence
                    ))

            stale_attr_ids = [aid for fp, aid in existing_attrs.items() if fp not in current_attr_fingerprints]
            if stale_attr_ids:
                cur.execute("DELETE FROM structured_attributes WHERE id = ANY(%s)", (stale_attr_ids,))

        stale_entity_ids = [eid for fp, eid in existing_entities.items() if fp not in current_entity_fingerprints]
        if stale_entity_ids:
            cur.execute("DELETE FROM structured_entities WHERE id = ANY(%s)", (stale_entity_ids,))

    return run_id

def get_extraction_run_by_detail(
    conn, detail_id: int, extractor_version: str = STRUCTURED_EXTRACTOR_VERSION
) -> Optional[ExtractionRun]:
    """Retrieves an ExtractionRun along with all child entities, field evidence, and attributes."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT * FROM structured_extraction_runs
            WHERE detail_id = %s AND extractor_version = %s
        """, (detail_id, extractor_version))
        run_row = cur.fetchone()
        if not run_row:
            return None

        run_id = run_row["id"]
        cur.execute("""
            SELECT * FROM structured_entities
            WHERE run_id = %s
            ORDER BY id ASC
        """, (run_id,))
        entity_rows = [dict(r) for r in cur.fetchall()]

        entities: List[StructuredEntity] = []
        for ent_row in entity_rows:
            ent_id = ent_row["id"]

            # Field evidence retrieval
            cur.execute("""
                SELECT * FROM structured_entity_field_evidence
                WHERE entity_id = %s
                ORDER BY id ASC
            """, (ent_id,))
            ev_rows = [dict(r) for r in cur.fetchall()]
            field_evidence = [
                StructuredFieldEvidence(
                    field_name=ev["field_name"],
                    source_quote=ev["source_quote"],
                    evidence_fingerprint=ev["evidence_fingerprint"],
                )
                for ev in ev_rows
            ]

            # Attributes retrieval
            cur.execute("""
                SELECT * FROM structured_attributes
                WHERE entity_id = %s
                ORDER BY id ASC
            """, (ent_id,))
            attr_rows = [dict(r) for r in cur.fetchall()]

            attributes = [
                StructuredAttribute(
                    attribute_name=a["attribute_name"],
                    attribute_name_normalized=a["attribute_name_normalized"],
                    raw_value=a["raw_value"],
                    source_quote=a["source_quote"],
                    normalized_value=a["normalized_value"],
                    numeric_value=float(a["numeric_value"]) if a["numeric_value"] is not None else None,
                    unit_raw=a["unit_raw"],
                    unit_normalized=a["unit_normalized"],
                    confidence=float(a["confidence"]) if a["confidence"] is not None else None,
                    attribute_fingerprint=a["attribute_fingerprint"],
                )
                for a in attr_rows
            ]

            ent = StructuredEntity(
                product_name_raw=ent_row["product_name_raw"],
                source_quote=ent_row["source_quote"],
                entity_type=ent_row["entity_type"],
                product_name_normalized=ent_row["product_name_normalized"],
                manufacturer_raw=ent_row["manufacturer_raw"],
                manufacturer_normalized=ent_row["manufacturer_normalized"],
                brand_raw=ent_row["brand_raw"],
                brand_normalized=ent_row["brand_normalized"],
                product_line_raw=ent_row["product_line_raw"],
                product_line_normalized=ent_row["product_line_normalized"],
                model_article_raw=ent_row["model_article_raw"],
                model_article_normalized=ent_row["model_article_normalized"],
                quantity_raw=ent_row["quantity_raw"],
                quantity_value=float(ent_row["quantity_value"]) if ent_row["quantity_value"] is not None else None,
                quantity_unit_raw=ent_row["quantity_unit_raw"],
                quantity_unit_normalized=ent_row["quantity_unit_normalized"],
                unit_price_raw=ent_row["unit_price_raw"],
                unit_price_value=float(ent_row["unit_price_value"]) if ent_row["unit_price_value"] is not None else None,
                total_price_raw=ent_row["total_price_raw"],
                total_price_value=float(ent_row["total_price_value"]) if ent_row["total_price_value"] is not None else None,
                currency_raw=ent_row["currency_raw"],
                currency_code=ent_row["currency_code"],
                confidence=float(ent_row["confidence"]) if ent_row["confidence"] is not None else None,
                field_evidence=field_evidence,
                attributes=attributes,
                entity_fingerprint=ent_row["entity_fingerprint"],
            )
            entities.append(ent)

        run = ExtractionRun(
            detail_id=run_row["detail_id"],
            procurement_id=run_row["procurement_id"],
            category_code=run_row["category_code"],
            source_text_snapshot=run_row["source_text_snapshot"],
            source_validator_name=run_row["source_validator_name"],
            source_validator_version=run_row["source_validator_version"],
            source_validation_method=run_row["source_validation_method"],
            source_text_sha256=run_row["source_text_sha256"],
            match_id=run_row["match_id"],
            queue_id=run_row["queue_id"],
            subcategory_code=run_row["subcategory_code"],
            document_name=run_row["document_name"],
            archive_member_path=run_row["archive_member_path"],
            page_or_sheet=run_row["page_or_sheet"],
            row_number=run_row["row_number"],
            extractor_name=run_row["extractor_name"],
            extractor_version=run_row["extractor_version"],
            extraction_method=run_row["extraction_method"],
            prompt_version=run_row["prompt_version"],
            model_name=run_row["model_name"],
            status=run_row["status"],
            raw_response=run_row["raw_response"],
            error_code=run_row["error_code"],
            error_message=run_row["error_message"],
            entities=entities,
        )
        return run
