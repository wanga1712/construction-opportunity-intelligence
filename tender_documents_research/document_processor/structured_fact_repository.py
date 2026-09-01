"""
R4 Structured Product Fact Repository.
Provides database persistence and retrieval for ExtractionRun, StructuredEntity,
and StructuredAttribute in PostgreSQL document_intelligence DB.
"""

from typing import Any, Dict, List, Optional
import psycopg2.extras

from tender_documents_research.document_processor.structured_fact_contract import (
    ExtractionRun,
    StructuredEntity,
    StructuredAttribute,
    STRUCTURED_EXTRACTOR_VERSION,
)

def save_extraction_run(conn, run: ExtractionRun) -> int:
    """
    Persists an ExtractionRun along with its StructuredEntity and StructuredAttribute children.
    Idempotent: Uses ON CONFLICT for runs, entities, and attributes.
    Returns the assigned run_id.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # 1. Upsert Extraction Run
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
            ON CONFLICT (detail_id, extractor_version)
            DO UPDATE SET
                status = EXCLUDED.status,
                raw_response = EXCLUDED.raw_response,
                error_code = EXCLUDED.error_code,
                error_message = EXCLUDED.error_message,
                completed_at = NOW()
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

        # If re-running, clear existing entities for this run to avoid orphans
        cur.execute("DELETE FROM structured_entities WHERE run_id = %s", (run_id,))

        # 2. Insert Entities and Attributes
        for ent in run.entities:
            cur.execute("""
                INSERT INTO structured_entities (
                    run_id, detail_id, procurement_id, category_code, subcategory_code,
                    entity_fingerprint, entity_type,
                    manufacturer_raw, manufacturer_normalized,
                    brand_raw, brand_normalized,
                    product_line_raw, product_line_normalized,
                    product_name_raw, product_name_normalized,
                    model_article_raw, model_article_normalized,
                    quantity_value, quantity_unit_raw, quantity_unit_normalized,
                    unit_price_value, total_price_value, currency_code,
                    source_quote, confidence
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (run_id, entity_fingerprint)
                DO UPDATE SET
                    confidence = EXCLUDED.confidence
                RETURNING id
            """, (
                run_id, run.detail_id, run.procurement_id, run.category_code, run.subcategory_code,
                ent.entity_fingerprint, ent.entity_type,
                ent.manufacturer_raw, ent.manufacturer_normalized,
                ent.brand_raw, ent.brand_normalized,
                ent.product_line_raw, ent.product_line_normalized,
                ent.product_name_raw, ent.product_name_normalized,
                ent.model_article_raw, ent.model_article_normalized,
                ent.quantity_value, ent.quantity_unit_raw, ent.quantity_unit_normalized,
                ent.unit_price_value, ent.total_price_value, ent.currency_code,
                ent.source_quote, ent.confidence
            ))
            entity_id = cur.fetchone()["id"]

            for attr in ent.attributes:
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
                    ON CONFLICT (entity_id, attribute_fingerprint)
                    DO UPDATE SET
                        confidence = EXCLUDED.confidence
                """, (
                    entity_id, run_id, attr.attribute_fingerprint,
                    attr.attribute_name, attr.attribute_name_normalized,
                    attr.raw_value, attr.normalized_value, attr.numeric_value,
                    attr.unit_raw, attr.unit_normalized, attr.source_quote, attr.confidence
                ))

    return run_id

def get_extraction_run_by_detail(
    conn, detail_id: int, extractor_version: str = STRUCTURED_EXTRACTOR_VERSION
) -> Optional[ExtractionRun]:
    """Retrieves an ExtractionRun along with all child entities and attributes."""
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
                quantity_value=float(ent_row["quantity_value"]) if ent_row["quantity_value"] is not None else None,
                quantity_unit_raw=ent_row["quantity_unit_raw"],
                quantity_unit_normalized=ent_row["quantity_unit_normalized"],
                unit_price_value=float(ent_row["unit_price_value"]) if ent_row["unit_price_value"] is not None else None,
                total_price_value=float(ent_row["total_price_value"]) if ent_row["total_price_value"] is not None else None,
                currency_code=ent_row["currency_code"],
                confidence=float(ent_row["confidence"]) if ent_row["confidence"] is not None else None,
                attributes=attributes,
                entity_fingerprint=ent_row["entity_fingerprint"],
            )
            entities.append(ent)

        run = ExtractionRun(
            detail_id=run_row["detail_id"],
            procurement_id=run_row["procurement_id"],
            category_code=run_row["category_code"],
            source_text_snapshot=run_row["source_text_snapshot"],
            source_text_sha256=run_row["source_text_sha256"],
            match_id=run_row["match_id"],
            queue_id=run_row["queue_id"],
            subcategory_code=run_row["subcategory_code"],
            document_name=run_row["document_name"],
            archive_member_path=run_row["archive_member_path"],
            page_or_sheet=run_row["page_or_sheet"],
            row_number=run_row["row_number"],
            source_validator_name=run_row["source_validator_name"],
            source_validator_version=run_row["source_validator_version"],
            source_validation_method=run_row["source_validation_method"],
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
