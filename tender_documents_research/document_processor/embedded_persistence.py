"""Idempotent persistence of EMBEDDED_EXTRACTOR_V1 facts (shared by callers)."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Iterable, Optional, Tuple

from document_processor.embedded_extraction import EXTRACTOR_VERSION
from document_processor.embedded_extraction import NORMALIZER_VERSION


def record_outcome(
    conn,
    *,
    source_document_id,
    procurement_id: int,
    category_code,
    track,
    document_name,
    outcome: str,
    facts_found: int = 0,
    reason=None,
    files_parsed: int = 0,
    files_failed: int = 0,
    member_count=None,
    bytes_value=None,
    artifact_class=None,
) -> None:
    """Version-scoped per-document extraction outcome (no-findings memory)."""
    if source_document_id is None:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO document_extraction_outcomes
                (source_document_id, procurement_id, category_code, track, document_name,
                 artifact_class, extractor_version, normalizer_version, outcome, facts_found,
                 member_count, bytes, reason, files_parsed, files_failed, updated_at, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
            ON CONFLICT (source_document_id, extractor_version, COALESCE(category_code, ''))
            DO UPDATE SET
                outcome = EXCLUDED.outcome,
                facts_found = EXCLUDED.facts_found,
                reason = EXCLUDED.reason,
                files_parsed = EXCLUDED.files_parsed,
                files_failed = EXCLUDED.files_failed,
                member_count = COALESCE(EXCLUDED.member_count, document_extraction_outcomes.member_count),
                bytes = COALESCE(EXCLUDED.bytes, document_extraction_outcomes.bytes),
                artifact_class = COALESCE(EXCLUDED.artifact_class, document_extraction_outcomes.artifact_class),
                updated_at = NOW()
            """,
            (
                int(source_document_id), procurement_id, category_code, track, document_name,
                artifact_class, EXTRACTOR_VERSION, NORMALIZER_VERSION, outcome, int(facts_found),
                member_count, bytes_value, (reason or "")[:400], files_parsed, files_failed,
            ),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def persist_facts(
    conn,
    *,
    procurement_id: int,
    document_name: str,
    category_code: str,
    facts: Iterable[Any],
    detail_id=None,
    source_text: Optional[str] = None,
    source_document_id: Optional[int] = None,
) -> Tuple[int, int, Dict[str, int]]:
    """Insert facts for one document; re-runs reuse entities (idempotent)."""
    facts = list(facts)
    stats = {"material": 0, "quantity": 0, "unit": 0, "unit_price": 0, "total": 0,
             "with_category": 0, "without_provenance": 0}
    if not facts:
        return 0, 0, stats
    cur = conn.cursor()
    if detail_id is None:
        cur.execute("SELECT MIN(id) FROM document_match_details WHERE procurement_id=%s", (procurement_id,))
        detail_id = cur.fetchone()[0]
    # GOOD_SUPPLY_FACTS_V1 Phase 1: для EMBEDDED храним bounded raw text
    # документа (source_quote — его подстрока), а не первые 200 JSON-цитат.
    # Fallback на прежний JSON-список сохранён для DIRECT и старых вызовов.
    if source_text and source_text.strip():
        # Крупные сметы (148391: 22k+ строк) не помещаются в 1M символов;
        # 10M покрывает такие документы, оставаясь bounded. PostgreSQL TOAST
        # сжимает snapshot, поэтому это приемлемо для canary/точечных reparse.
        max_chars = int(os.getenv("PROVENANCE_SNAPSHOT_MAX_CHARS", "10000000"))
        snapshot = source_text[:max_chars]
    else:
        snapshot = json.dumps([f.source_quote for f in facts][:200], ensure_ascii=False)
    # GOOD_SUPPLY_FACTS_V1: run identity is per source document. The same
    # file_name can appear top-level and inside an archive; document_name alone
    # merged those runs and their snapshots overwrote each other.
    if source_document_id is not None:
        cur.execute(
            "SELECT id FROM structured_extraction_runs"
            " WHERE procurement_id=%s AND source_document_id=%s AND extractor_version=%s"
            " LIMIT 1",
            (procurement_id, int(source_document_id), EXTRACTOR_VERSION),
        )
    else:
        cur.execute(
            "SELECT id FROM structured_extraction_runs"
            " WHERE procurement_id=%s AND document_name=%s AND extractor_version=%s"
            "   AND source_document_id IS NULL LIMIT 1",
            (procurement_id, document_name, EXTRACTOR_VERSION),
        )
    row = cur.fetchone()
    if row:
        run_id = row[0]
        cur.execute(
            "UPDATE structured_extraction_runs SET category_code=%s, source_text_snapshot=%s,"
            " source_text_sha256=%s, completed_at=NOW() WHERE id=%s",
            (str(category_code)[:100], snapshot,
             hashlib.sha256(snapshot.encode("utf-8")).hexdigest(), run_id),
        )
    else:
        if source_document_id is not None:
            conflict_clause = (
                "ON CONFLICT (procurement_id, source_document_id, extractor_version)"
                " WHERE source_document_id IS NOT NULL DO UPDATE SET"
            )
        else:
            conflict_clause = (
                "ON CONFLICT (detail_id, extractor_version)"
                " WHERE source_document_id IS NULL DO UPDATE SET"
            )
        cur.execute(
            f"""
            INSERT INTO structured_extraction_runs
                (detail_id, procurement_id, source_document_id, category_code, document_name,
                 page_or_sheet, source_text_snapshot, source_text_sha256, source_validator_name,
                 source_validator_version, source_validation_method, extractor_name,
                 extractor_version, extraction_method, prompt_version, model_name, status,
                 created_at, completed_at, structured_fact_trust_state)
             VALUES (%s,%s,%s,%s,%s,'mixed',%s,%s,'PROVENANCE_CONTRACT','v1','PARSE_TIME',
                     'EMBEDDED_EXTRACTOR',%s,'DETERMINISTIC_ROW_MAP','none','none','COMPLETED',
                     NOW(),NOW(),'MANUAL_PROOF_QUARANTINE')
             {conflict_clause}
                 category_code = EXCLUDED.category_code,
                 source_document_id = EXCLUDED.source_document_id,
                 document_name = EXCLUDED.document_name,
                 source_text_snapshot = EXCLUDED.source_text_snapshot,
                 source_text_sha256 = EXCLUDED.source_text_sha256,
                 completed_at = NOW()
             RETURNING id
            """,
            (detail_id, procurement_id, source_document_id, str(category_code)[:100],
             document_name, snapshot,
             hashlib.sha256(snapshot.encode("utf-8")).hexdigest(), EXTRACTOR_VERSION),
        )
        run_id = cur.fetchone()[0]

    created = reused = 0
    for f in facts:
        unit_raw = (f.unit_raw or None) and str(f.unit_raw)[:100]
        unit_norm = (f.unit_normalized or None) and str(f.unit_normalized)[:100]
        cat = str(f.category_code or "unknown")[:100]
        cur.execute(
            """
            INSERT INTO structured_entities
                (run_id, detail_id, procurement_id, category_code, entity_fingerprint,
                 entity_type, product_name_raw, product_name_normalized,
                 quantity_value, quantity_raw, quantity_unit_raw, quantity_unit_normalized,
                 measurement_family, unit_price_value, unit_price_raw,
                 total_price_value, total_price_raw, currency_code, source_quote,
                 confidence, product_relation, created_at, structured_fact_trust_state,
                 source_document_id, physical_download_key, page_or_sheet, row_or_line,
                 extractor_version, normalizer_version, layout_status,
                 section_code, section_name, section_total_price_value,
                 section_total_price_raw, section_total_source)
            VALUES (%s,%s,%s,%s,%s,'PRODUCT',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RUB',%s,
                    %s,'EMBEDDED',NOW(),'MANUAL_PROOF_QUARANTINE',%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s)
            ON CONFLICT (procurement_id, source_document_id, entity_fingerprint, extractor_version)
              WHERE extractor_version IS NOT NULL AND source_document_id IS NOT NULL
            DO UPDATE SET
                -- Provenance: сущность должна ссылаться на run того документа,
                -- из которого она реально извлечена при reparse.
                run_id = EXCLUDED.run_id,
                detail_id = EXCLUDED.detail_id,
                quantity_value = EXCLUDED.quantity_value,
                quantity_unit_normalized = EXCLUDED.quantity_unit_normalized,
                measurement_family = EXCLUDED.measurement_family,
                unit_price_value = EXCLUDED.unit_price_value,
                total_price_value = EXCLUDED.total_price_value,
                total_price_raw = EXCLUDED.total_price_raw,
                layout_status = EXCLUDED.layout_status,
                source_quote = EXCLUDED.source_quote,
                -- SECTION_LEVEL_NORMALIZATION_V1 (Phase 2)
                section_code = EXCLUDED.section_code,
                section_name = EXCLUDED.section_name,
                section_total_price_value = EXCLUDED.section_total_price_value,
                section_total_price_raw = EXCLUDED.section_total_price_raw,
                section_total_source = EXCLUDED.section_total_source
               WHERE %s
             RETURNING id
             """,
            (
                run_id, detail_id, procurement_id, cat, f.entity_fingerprint,
                (f.product_name_raw or "")[:400], f.product_name_normalized,
                f.quantity_value, f.quantity_raw, unit_raw, unit_norm,
                f.measurement_family, f.unit_price_value, f.unit_price_raw,
                f.line_total_value, f.line_total_raw, f.source_quote, f.confidence,
                f.source_document_id, f.physical_download_key, f.page_or_sheet,
                f.row_or_line, f.extractor_version, f.normalizer_version,
                getattr(f, "layout_status", None),
                getattr(f, "section_code", None),
                getattr(f, "section_name", None),
                getattr(f, "section_total_price_value", None),
                getattr(f, "section_total_price_raw", None),
                getattr(f, "section_total_source", None),
                os.getenv("EMBEDDED_FORCE_UPDATE", "0") == "1",
            ),
        )
        entity_row = cur.fetchone()
        if cur.rowcount == 0:
            cur.execute(
                "SELECT id FROM structured_entities"
                " WHERE procurement_id=%s AND source_document_id IS NOT DISTINCT FROM %s"
                " AND entity_fingerprint=%s AND extractor_version=%s LIMIT 1",
                (procurement_id, f.source_document_id, f.entity_fingerprint, f.extractor_version),
            )
            entity_id = cur.fetchone()[0]
            reused += 1
        else:
            entity_id = entity_row[0]
            created += 1
        if f.product_name_raw:
            stats["material"] += 1
        if f.quantity_value is not None:
            stats["quantity"] += 1
        if f.unit_normalized:
            stats["unit"] += 1
        if f.unit_price_value is not None:
            stats["unit_price"] += 1
        if f.line_total_value is not None:
            stats["total"] += 1
        if cat and cat != "unknown":
            stats["with_category"] += 1
        if not (f.source_document_id and f.source_quote):
            stats["without_provenance"] += 1
        if getattr(f, "attributes", None):
            for a in f.attributes:
                cur.execute(
                    """
                    INSERT INTO structured_attributes
                        (entity_id, run_id, attribute_fingerprint, attribute_name,
                         attribute_name_normalized, raw_value, normalized_value, numeric_value,
                         unit_raw, unit_normalized, source_quote, confidence, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (entity_id, attribute_fingerprint) DO UPDATE SET
                        attribute_name = EXCLUDED.attribute_name,
                        attribute_name_normalized = EXCLUDED.attribute_name_normalized,
                        raw_value = EXCLUDED.raw_value,
                        normalized_value = EXCLUDED.normalized_value,
                        numeric_value = EXCLUDED.numeric_value,
                        unit_raw = EXCLUDED.unit_raw,
                        unit_normalized = EXCLUDED.unit_normalized,
                        source_quote = EXCLUDED.source_quote,
                        confidence = EXCLUDED.confidence
                    """,
                    (
                        entity_id, run_id, a.attribute_fingerprint, a.attribute_name,
                        a.attribute_name_normalized, a.raw_value, a.normalized_value,
                        a.numeric_value, a.unit_raw, a.unit_normalized, a.source_quote,
                        a.confidence,
                    ),
                )
    return created, reused, stats
