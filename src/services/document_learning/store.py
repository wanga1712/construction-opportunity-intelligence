"""Persist document observations. No runtime DDL. No downloads."""
from __future__ import annotations

import json
from typing import Any

from src.services.document_learning.contract import DocumentObservation

_INSERT_SQL = """
INSERT INTO crm_v3_document_observations (
    observation_key, procurement_id, source_contour, source_document_id,
    source_document_url, document_title, source_document_type, file_extension,
    mime_type, source_section, procurement_form, object_type, object_context,
    commercial_candidate_categories, okpd_context, procurement_lifecycle,
    document_ordinal, document_count, download_status, parse_status, file_size,
    page_count, text_length, commercial_evidence_found, evidence_count,
    matched_categories, matched_subcategories, matched_terms, product_mentions,
    specification_evidence, estimate_evidence, volume_quantity_evidence,
    numeric_unit_evidence, usefulness_label, acquisition_policy,
    acquisition_policy_version, extractor_version, matcher_version,
    taxonomy_version, selector_model_version, calibration_truth
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s
)
ON CONFLICT (observation_key) DO UPDATE SET
    download_status = EXCLUDED.download_status,
    parse_status = EXCLUDED.parse_status,
    file_size = EXCLUDED.file_size,
    page_count = EXCLUDED.page_count,
    text_length = EXCLUDED.text_length,
    commercial_evidence_found = EXCLUDED.commercial_evidence_found,
    evidence_count = EXCLUDED.evidence_count,
    matched_categories = EXCLUDED.matched_categories,
    matched_subcategories = EXCLUDED.matched_subcategories,
    matched_terms = EXCLUDED.matched_terms,
    product_mentions = EXCLUDED.product_mentions,
    specification_evidence = EXCLUDED.specification_evidence,
    estimate_evidence = EXCLUDED.estimate_evidence,
    volume_quantity_evidence = EXCLUDED.volume_quantity_evidence,
    numeric_unit_evidence = EXCLUDED.numeric_unit_evidence,
    usefulness_label = EXCLUDED.usefulness_label,
    extractor_version = EXCLUDED.extractor_version,
    matcher_version = EXCLUDED.matcher_version,
    taxonomy_version = EXCLUDED.taxonomy_version,
    selector_model_version = EXCLUDED.selector_model_version,
    calibration_truth = EXCLUDED.calibration_truth
RETURNING id
"""


def _json(value: list[str]) -> str:
    return json.dumps(value)


def insert_observation(observation: DocumentObservation, crm_db: Any) -> int | None:
    record = observation.to_record()
    params = (
        record["observation_key"],
        record["procurement_id"],
        record["source_contour"],
        record["source_document_id"],
        record["source_document_url"],
        record["document_title"],
        record["source_document_type"],
        record["file_extension"],
        record["mime_type"],
        record["source_section"],
        record["procurement_form"],
        record["object_type"],
        record["object_context"],
        _json(record["commercial_candidate_categories"]),
        record["okpd_context"],
        record["procurement_lifecycle"],
        record["document_ordinal"],
        record["document_count"],
        record["download_status"],
        record["parse_status"],
        record["file_size"],
        record["page_count"],
        record["text_length"],
        record["commercial_evidence_found"],
        record["evidence_count"],
        _json(record["matched_categories"]),
        _json(record["matched_subcategories"]),
        _json(record["matched_terms"]),
        _json(record["product_mentions"]),
        record["specification_evidence"],
        record["estimate_evidence"],
        record["volume_quantity_evidence"],
        record["numeric_unit_evidence"],
        record["usefulness_label"],
        record["acquisition_policy"],
        record["acquisition_policy_version"],
        record["extractor_version"],
        record["matcher_version"],
        record["taxonomy_version"],
        record["selector_model_version"],
        record["calibration_truth"],
    )
    if hasattr(crm_db, "execute_query"):
        rows = crm_db.execute_query(_INSERT_SQL, params)
        if rows:
            row = rows[0]
            if isinstance(row, dict):
                return next(iter(row.values()))
            return row[0]
        return None
    crm_db.execute_update(_INSERT_SQL, params)
    return None
